"""
Voice assistant loop for the Raspberry Pi - faster-whisper version.

Flow:
  1. Listen to the USB mic continuously.
  2. Use simple voice-activity detection (webrtcvad) to figure out when
     you start and stop speaking.
  3. Once a phrase ends, transcribe the captured audio with faster-whisper
     (offline, on-device).
  4. Send the transcribed text over WiFi to your LLM server.
  5. Speak the reply back using Piper, and forward the LLM's chosen
     emotion to RoboEyes.

REQUIREMENTS (install inside this venv):
    pip install faster-whisper sounddevice requests webrtcvad numpy

You'll also need:
  - Piper installed and a voice model downloaded
  - LLM_SERVER_URL updated to point at your other device's IP
  - portaudio installed at the OS level (sudo apt install portaudio19-dev)
"""

import collections
import subprocess
import sys

import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel

# --- CONFIGURATION - EDIT THESE ---
WHISPER_MODEL_SIZE = "base"                        # "tiny" or "base" recommended for Pi 5 real-time use
WHISPER_COMPUTE_TYPE = "int8"                      # int8 is fastest on CPU-only ARM (Pi 5 has no usable GPU path)
LLM_SERVER_URL = "http://192.168.1.195:5000/chat"  # replace with your LLM device's actual IP
PIPER_BINARY = "piper"
PIPER_VOICE_MODEL = "en_US-lessac-medium.onnx"

SAMPLE_RATE = 16000        # required by both webrtcvad and whisper
MIC_NAME_HINT = "USB PnP Sound Device"  # substring to search for among input devices
MIC_NATIVE_SAMPLE_RATE = None  # set automatically at startup based on the mic's actual capabilities
FRAME_MS = 30              # webrtcvad requires 10, 20, or 30 ms frames
VAD_AGGRESSIVENESS = 2     # 0 (least aggressive) to 3 (most aggressive) filtering of non-speech
SILENCE_FRAMES_TO_STOP = 20  # ~600ms of silence (20 * 30ms) ends a phrase
MIN_SPEECH_FRAMES = 5       # ignore very short blips/noise

ROBOEYES_UDP_IP = "127.0.0.1"
ROBOEYES_UDP_PORT = 5005

EMOTION_TO_ROBOEYES = {
    "happy": "HAPPY",
    "excited": "HAPPY",
    "joyful": "HAPPY",
    "angry": "ANGRY",
    "frustrated": "ANGRY",
    "annoyed": "ANGRY",
    "tired": "TIRED",
    "sleepy": "TIRED",
    "bored": "TIRED",
    "confused": "CONFUSED",
    "unsure": "CONFUSED",
    "neutral": "DEFAULT",
    "calm": "DEFAULT",
    "laughing": "LAUGH",
    "amused": "LAUGH",
    "sad": "SAD",
    "listening": "LISTENING"
}


def send_mood_to_roboeyes(mood: str):
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(mood.encode("utf-8"), (ROBOEYES_UDP_IP, ROBOEYES_UDP_PORT))
    except Exception as e:
        print(f"[voice_assistant] Could not send mood to RoboEyes: {e}")


def map_emotion_to_roboeyes_mood(emotion: str) -> str:
    if not emotion:
        return "DEFAULT"
    return EMOTION_TO_ROBOEYES.get(emotion.strip().lower(), "DEFAULT")


def speak(text: str):
    print(f"[voice_assistant] Speaking: {text}")
    piper_proc = subprocess.Popen(
        [PIPER_BINARY, "--model", PIPER_VOICE_MODEL, "--output-raw"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    aplay_proc = subprocess.Popen(
        ["paplay", "--raw", "--rate=22050", "--format=s16le", "--channels=1"],
        stdin=piper_proc.stdout,
    )
    piper_proc.stdin.write(text.encode("utf-8"))
    piper_proc.stdin.close()
    aplay_proc.wait()


def ask_llm(user_text: str):
    try:
        response = requests.post(LLM_SERVER_URL, json={"text": user_text}, timeout=120)
        
        data = response.json()

        if response.status_code == 200:
            data = response.json()
            return data.get("reply", "Sorry, I didn't get a reply."), data.get("emotion")
 
        # Log the raw error body for debugging regardless of which case below fires
        print(f"[voice_assistant] LLM server returned {response.status_code}: {response.text}")
 
        if response.status_code == 400:
            return "I didn't quite catch that, could you try again?", "confused"
        elif response.status_code == 404:
            return "The assistant service isn't set up right on the other end.", "sad"
        elif response.status_code == 500:
            return "Something went wrong on the assistant's end. Let me know if it keeps happening.", "sad"
        elif response.status_code == 503:
            return "The assistant is busy right now, give it a moment.", "tired"
        else:
            return f"Got an unexpected error ({response.status_code}) from the assistant.", "sad"
    except requests.exceptions.Timeout:
        print("[voice_assistant] LLM server request timed out.")
        return "LLM server request timed out", "tired"
    except requests.exceptions.RequestException as e:
        print(f"[voice_assistant] Error reaching LLM server: {e}")
        return "Sorry, I couldn't reach the assistant right now.", "SAD"


def find_mic_device(name_hint: str) -> int:
    """
    Searches all audio devices for one matching name_hint that has at
    least one input channel, and returns its index. Raises a clear error
    if none is found, rather than failing later with a cryptic PortAudio
    error.
    """
    devices = sd.query_devices()
    for index, device in enumerate(devices):
        if name_hint.lower() in device["name"].lower() and device["max_input_channels"] > 0:
            return index
    raise RuntimeError(
        f"Could not find an input device matching '{name_hint}'. "
        f"Available devices:\n{devices}"
    )


def resample_to_16k(audio_int16: np.ndarray, orig_rate: int) -> np.ndarray:
    """
    Simple linear-interpolation resampler from the mic's native rate down
    to 16000 Hz, which webrtcvad and Whisper both require.
    """
    if orig_rate == SAMPLE_RATE:
        return audio_int16
    duration = len(audio_int16) / orig_rate
    target_length = int(duration * SAMPLE_RATE)
    orig_indices = np.linspace(0, len(audio_int16) - 1, num=len(audio_int16))
    target_indices = np.linspace(0, len(audio_int16) - 1, num=target_length)
    resampled = np.interp(target_indices, orig_indices, audio_int16).astype(np.int16)
    return resampled


def record_phrase(vad: webrtcvad.Vad, mic_device_index: int) -> bytes:
    """
    Records audio from the mic until a pause in speech is detected.
    Recording happens at the mic's native sample rate, then everything
    is resampled to 16000 Hz (required by webrtcvad and Whisper) before
    voice-activity detection and returning.
    """
    native_rate = MIC_NATIVE_SAMPLE_RATE
    frame_length_native = int(native_rate * FRAME_MS / 1000)

    ring_buffer = collections.deque(maxlen=SILENCE_FRAMES_TO_STOP)
    voiced_frames = []
    triggered = False
    silence_count = 0
    speech_count = 0

    with sd.RawInputStream(
        samplerate=native_rate,
        blocksize=frame_length_native,
        dtype="int16",
        channels=1,
        device=mic_device_index,
    ) as stream:
        print("[voice_assistant] Listening for speech...")
        while True:
            frame, _ = stream.read(frame_length_native)
            frame_np = np.frombuffer(bytes(frame), dtype=np.int16)
            frame_16k = resample_to_16k(frame_np, native_rate)

            # webrtcvad needs exactly 10/20/30ms of 16kHz audio - pad/trim just in case
            expected_len = int(SAMPLE_RATE * FRAME_MS / 1000)
            if len(frame_16k) < expected_len:
                frame_16k = np.pad(frame_16k, (0, expected_len - len(frame_16k)))
            elif len(frame_16k) > expected_len:
                frame_16k = frame_16k[:expected_len]

            frame_bytes = frame_16k.tobytes()
            is_speech = vad.is_speech(frame_bytes, SAMPLE_RATE)

            if not triggered:
                ring_buffer.append(frame_bytes)
                if is_speech:
                    speech_count += 1
                    if speech_count >= MIN_SPEECH_FRAMES:
                        triggered = True
                        voiced_frames.extend(ring_buffer)
                        ring_buffer.clear()
                        print("[voice_assistant] Speech detected, recording...")
                else:
                    speech_count = 0
            else:
                voiced_frames.append(frame_bytes)
                if is_speech:
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_FRAMES_TO_STOP:
                        print("[voice_assistant] End of speech detected.")
                        break

    return b"".join(voiced_frames)


def transcribe(model: WhisperModel, audio_bytes: bytes) -> str:
    """
    Converts raw int16 PCM bytes into the float32 format faster-whisper
    expects, then transcribes it.
    """
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio_np, language="en", beam_size=1)
    text = " ".join(segment.text.strip() for segment in segments)
    return text.strip()


def main():
    global MIC_NATIVE_SAMPLE_RATE

    print("[voice_assistant] Loading faster-whisper model...")
    model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)

    mic_device_index = find_mic_device(MIC_NAME_HINT)
    device_info = sd.query_devices(mic_device_index)
    MIC_NATIVE_SAMPLE_RATE = int(device_info["default_samplerate"])
    print(f"[voice_assistant] Using mic device {mic_device_index} ({device_info['name']}) "
          f"at native rate {MIC_NATIVE_SAMPLE_RATE} Hz, resampling to {SAMPLE_RATE} Hz")

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    print("[voice_assistant] Ready. Speak whenever you like. (Ctrl+C to stop)")
    send_mood_to_roboeyes("DEFAULT")  # initial "listening" face

    while True:
        audio_bytes = record_phrase(vad, mic_device_index)
        send_mood_to_roboeyes("LISTENING")  # keep "listening" face
        print("[voice_assistant] Transcribing...")
        text = transcribe(model, audio_bytes)

        if not text:
            print("[voice_assistant] (No speech recognized, listening again)")
            continue

        print(f"[voice_assistant] Heard: {text}")
        speak(f"You said: {text}")  # echoes back what it transcribed, for confirmation

        send_mood_to_roboeyes("DEFAULT")  # "thinking" face while waiting

        reply, emotion = ask_llm(text)

        mood = map_emotion_to_roboeyes_mood(emotion)
        print(f"[voice_assistant] LLM emotion: {emotion} -> RoboEyes mood: {mood}")
        send_mood_to_roboeyes(mood)
        speak(reply)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[voice_assistant] Stopped.")