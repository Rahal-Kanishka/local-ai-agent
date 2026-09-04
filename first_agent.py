import ollama
import sys

print("Question: ", sys.argv[1])
question = sys.argv[1]

import requests

def get_weather(city: str) -> str:
    print('Get weather called: ', city)

    # Step 1: city name -> lat/lon
    geo_resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1}
    )
    geo_data = geo_resp.json()

    if "results" not in geo_data or not geo_data["results"]:
        return f"ERROR: could not find location for '{city}'"

    result = geo_data["results"][0]
    lat, lon = result["latitude"], result["longitude"]
    resolved_name = result.get("name", city)
    country = result.get("country", "")

    # Step 2: lat/lon -> current weather
    weather_resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m"
        }
    )
    weather_data = weather_resp.json()

    if "current" not in weather_data:
        return f"ERROR: weather API returned no current data for {resolved_name}"

    temp = weather_data["current"]["temperature_2m"]
    wind = weather_data["current"]["wind_speed_10m"]

    return f"{temp}°C, wind {wind} km/h in {resolved_name}, {country}"

def get_device_temp() -> str:
    print('Get Device temp')
    file = open("/sys/class/thermal/thermal_zone0/temp", "r")

    # Read the entire content of the file
    content = file.read()
    intvalue = int(content)
    if intvalue == 0:
        return "0°C"
    celsius = intvalue / 1000
    return f"Device Temperature: {celsius:.1f}°C"

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

messages = [
    {"role": "system", "content": "You have tools available. If answering the "
     "question requires information you don't already have (like current weather "
     "or device temperature), call the relevant tool(s) instead of guessing or "
     "speaking generally. Call as many tools as needed before answering."},
    {"role": "user", "content": question}
]

print('AI is thinking...')

response = ollama.chat(
    model="llama3.1:8b",
    messages=messages,
    tools=tools
)

message = response["message"]
print('AI Response: ', response)
MAX_TRIES = 5
while message.get("tool_calls") and MAX_TRIES > 0:
    if message.get("tool_calls"):
        tool_results = []
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
            tool_results.append(result)
                
        # feed results back to model for final answer
        print("AI is processing the results ...")
        followup = ollama.chat(
            model="llama3.1:8b",
            messages=[
                {"role": "user", "content": question},
                message,
                {"role": "tool", "content": ", ".join(tool_results)}
            ]
        )
        print(followup["message"]["content"])
        message = followup["message"]
        print('AI Response for tools: ', followup["message"].get("tool_calls"))

        # check if the model is calling tools again, if so, loop again
        if followup["message"].get("tool_calls") and MAX_TRIES > 0:
            print("AI is recalling tools ...", followup)
            MAX_TRIES -= 1
        else:
            break
    else:
        print(message["content"])

