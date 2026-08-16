import ollama
import sys

print("Question: ", sys.argv[1])
question = sys.argv[1]

def get_weather(city: str) -> str:
    print('Get wheather called: ', city)
    # in real life, call a weather API here
    return f"It's 72°F and sunny in {city}"

def get_device_temp() -> str:
    print('Get Device temp')
    file = open("/sys/class/thermal/thermal_zone0/temp", "r")

    # Read the entire content of the file
    content = file.read()
    intvalue = int(content)
    if intvalue == 0:
        return "0°C"
    celsius = intvalue / 1000
    return f"{celsius:.1f}°C"

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "get_device_temperature",
        "description": "Get current Temperture of the device",
        "parameters": {
        }
    }
}]

response = ollama.chat(
    model="llama3.1:8b",
    messages=[{"role": "user", "content": question}],
    tools=tools
)

message = response["message"]
print('AI Response: ', message)

if message.get("tool_calls"):
    for call in message["tool_calls"]:
        if call["function"]["name"] == "get_weather":
            args = call["function"]["arguments"]
            result = get_weather(**args)
        elif call["function"]["name"] == "get_device_temperature":
            args = call["function"]["arguments"]
            result = get_device_temp()
        else:
            tool = call["function"]["name"]
            result = f"Unknown Tool {tool}"
        print("Tool result:", result)
            
        # feed result back to model for final answer
        print("AI is processing the results ...")
        followup = ollama.chat(
            model="llama3.1:8b",
            messages=[
                {"role": "user", "content": question},
                message,
                {"role": "tool", "content": result}
            ]
        )
        print(followup["message"]["content"])
else:
    print(message["content"])

