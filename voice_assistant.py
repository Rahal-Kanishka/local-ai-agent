"""
Voice assistant loop for the Raspberry Pi.

Flow:
  1. Listen to the USB mic continuously.
  2. Use Vosk to transcribe speech to text, in real time, offline.
  3. When a finished phrase is detected, send it over WiFi to your
     LLM server (running on the other device).
  4. Speak the reply back using Piper.

REQUIREMENTS (install inside your venv):
    pip install vosk sounddevice requests

You'll also need:
  - The Vosk model folder downloaded and unzipped somewhere (see setup steps earlier)
  - Piper installed and a voice model downloaded
  - LLM_SERVER_URL updated to point at your other device's IP
"""

import json
import queue
import subprocess
import sys

import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# --- CONFIGURATION - EDIT THESE ---
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"   # path to the unzipped model folder
LLM_SERVER_URL = "http://192.168.1.195:5000/chat"  # replace with your LLM device's actual IP
PIPER_BINARY = "piper"                             # or full path to the piper binary
PIPER_VOICE_MODEL = "en_US-lessac-medium.onnx"     # path to your downloaded voice model
SAMPLE_RATE = 16000

# Optional: same UDP setup as your RoboEyes script, so this can also
# change the eyes' mood while talking. Set to None to disable.
ROBOEYES_UDP_IP = "127.0.0.1"
ROBOEYES_UDP_PORT = 5005


def send_mood_to_roboeyes(mood: str):
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(mood.encode("utf-8"), (ROBOEYES_UDP_IP, ROBOEYES_UDP_PORT))
    except Exception as e:
        print(f"[voice_assistant] Could not send mood to RoboEyes: {e}")


def speak(text: str):
    """
    Sends text to Piper for offline speech synthesis and plays it aloud.
    """
    print(f"[voice_assistant] Speaking: {text}")
    # Piper reads text on stdin and writes audio to stdout by default when
    # given --output_raw or a file; here we pipe straight to aplay for playback.
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



# Maps whatever emotion labels your LLM's tool call returns to the
# mood commands RoboEyes actually understands (HAPPY, ANGRY, TIRED,
# DEFAULT, CONFUSED, LAUGH). Add/edit entries to match your tool's
# exact output values.
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


def map_emotion_to_roboeyes_mood(emotion: str) -> str:
    if not emotion:
        return "DEFAULT"
    return EMOTION_TO_ROBOEYES.get(emotion.strip().lower(), "DEFAULT")


def ask_llm(user_text: str):
    """
    Sends transcribed text to the LLM server running on the other device.
    Returns a tuple: (reply_text, emotion)
    """
    try:
        response = requests.post(LLM_SERVER_URL, json={"text": user_text}, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("reply", "Sorry, I didn't get a reply."), data.get("emotion")
    except requests.exceptions.RequestException as e:
        print(f"[voice_assistant] Error reaching LLM server: {e}")
        return "Sorry, I couldn't reach the assistant right now.", None


def main():
    print("[voice_assistant] Loading Vosk model...")
    model = Model(VOSK_MODEL_PATH)
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        if status:
            print(f"[voice_assistant] Audio status: {status}", file=sys.stderr)
        audio_queue.put(bytes(indata))

    print("[voice_assistant] Listening... (Ctrl+C to stop)")
    send_mood_to_roboeyes("DEFAULT")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=8000,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        while True:
            data = audio_queue.get()
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()

                if text:
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