"""
Minimal Flask wrapper around your existing Ollama tool-calling script.

HOW TO ADAPT THIS:
Replace the `get_response_from_model` function body with whatever your
existing script already does to go from user text -> model reply.
If your script currently looks like:

    def process_message(text):
        ...
        return reply

...then just call that function here instead of the placeholder.
"""

from flask import Flask, request, jsonify
from first_agent import process_message  # import the first agent

app = Flask(__name__)

# --- IMPORT YOUR EXISTING SCRIPT'S LOGIC HERE ---
# Example: if your script is called assistant_brain.py in the same folder
# and has a function `process_message(text) -> str`, do:
#
#   from assistant_brain import process_message
#
# Then replace the placeholder function below with a call to it.


def get_response_from_model(user_text: str):
    """
    Placeholder - replace this with your actual Ollama tool-calling logic.

    Must return a tuple: (reply_text, emotion)

    `emotion` should come from whatever tool call your model makes to
    decide the emotional tone of its response, e.g. "happy", "confused",
    "angry", "tired", "neutral". Return None if no emotion was determined.
    """
    # Example placeholder behavior (replace with your real logic):
    #
    #   from assistant_brain import process_message
    #   reply_text, emotion = process_message(user_text)
    #   return reply_text, emotion
    #
    # If your tool-calling setup returns emotion as part of a larger
    # structured response (e.g. a dict), just pull it out here, e.g.:
    #
    print(f"[llm_server] Processing message: {user_text}")
    result = ''
    try:
        result = process_message(user_text)
        print(f"[llm_server] Model reply: {result['reply']}, emotion: {result.get('emotion')}") 
    except Exception as e:
        print(f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}")

    
    return result["reply"], result.get("emotion")

    # return f"You said: {user_text}", "neutral"


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_text = data.get("text", "").strip()

    if not user_text:
        return jsonify({"error": "No 'text' field provided"}), 400
    
    print(f"[llm_server] Received user text: {user_text}")

    try:
        reply, emotion = get_response_from_model(user_text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"reply": reply, "emotion": emotion})


if __name__ == "__main__":
    # 0.0.0.0 makes it reachable from other devices on the same WiFi (like your Pi)
    # Port 5000 is Flask's default - change if it clashes with something else
    app.run(host="0.0.0.0", port=5000)