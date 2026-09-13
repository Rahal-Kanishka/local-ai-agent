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
WHISPER_MODEL_SIZE = "tiny"                        # "tiny" or "base" recommended for Pi 5 real-time use
WHISPER_COMPUTE_TYPE = "int8"                      # int8 is fastest on CPU-only ARM (Pi 5 has no usable GPU path)
LLM_SERVER_URL = "http://192.168.1.XXX:5000/chat"  # replace with your LLM device's actual IP
PIPER_BINARY = "piper"
PIPER_VOICE_MODEL = "en_US-lessac-medium.onnx"

SAMPLE_RATE = 16000        # required by both webrtcvad and whisper
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
        ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"],
        stdin=piper_proc.stdout,
    )
    piper_proc.stdin.write(text.encode("utf-8"))
    piper_proc.stdin.close()
    aplay_proc.wait()


def ask_llm(user_text: str):
    try:
        response = requests.post(LLM_SERVER_URL, json={"text": user_text}, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("reply", "Sorry, I didn't get a reply."), data.get("emotion")
    except requests.exceptions.RequestException as e:
        print(f"[voice_assistant] Error reaching LLM server: {e}")
        return "Sorry, I couldn't reach the assistant right now.", None


def record_phrase(vad: webrtcvad.Vad) -> bytes:
    """
    Records audio from the mic until a pause in speech is detected.
    Returns raw int16 PCM bytes of just the spoken phrase.
    """
    frame_length = int(SAMPLE_RATE * FRAME_MS / 1000)  # samples per frame
    ring_buffer = collections.deque(maxlen=SILENCE_FRAMES_TO_STOP)

    voiced_frames = []
    triggered = False
    silence_count = 0
    speech_count = 0

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=frame_length,
        dtype="int16",
        channels=1,
    ) as stream:
        print("[voice_assistant] Listening for speech...")
        while True:
            frame, _ = stream.read(frame_length)
            frame_bytes = bytes(frame)
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
    print("[voice_assistant] Loading faster-whisper model...")
    model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    print("[voice_assistant] Ready. Speak whenever you like. (Ctrl+C to stop)")
    send_mood_to_roboeyes("DEFAULT")

    while True:
        audio_bytes = record_phrase(vad)

        print("[voice_assistant] Transcribing...")
        text = transcribe(model, audio_bytes)

        if not text:
            print("[voice_assistant] (No speech recognized, listening again)")
            continue

        print(f"[voice_assistant] Heard: {text}")
        send_mood_to_roboeyes("CONFUSED")  # "thinking" face while waiting

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