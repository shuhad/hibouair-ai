from flask import Flask, request, jsonify, render_template
import json
import subprocess
import time
from datetime import datetime
from multiprocessing import Process, Manager
from bleuio_lib.bleuio_funcs import BleuIO

app = Flask(__name__)

# HibouAir Board ID
BOARD_ID = "220069"

def adv_data_decode(adv):
    """Decode CO2, pressure, temperature, and humidity from the advertisement data."""
    try:
        pos = adv.find("5B0705")
        if pos == -1:
            raise ValueError("Invalid advertisement data: '5B0705' not found.")

        # CO2 level
        co2 = int(adv[pos + 46:pos + 50], 16)

        # Pressure (convert from little-endian)
        pressure_bytes = bytes.fromhex(adv[pos + 18:pos + 22])
        pressure = int.from_bytes(pressure_bytes, byteorder="little") / 10

        # Temperature (convert from little-endian)
        temp_hex = int(adv[pos + 22:pos + 26][::-1], 16)
        if temp_hex > 1000:
            temperature = (temp_hex - (65535 + 1)) / 10
        else:
            temperature = temp_hex / 10

        # Humidity (convert from little-endian)
        humidity_bytes = bytes.fromhex(adv[pos + 26:pos + 30])
        humidity = int.from_bytes(humidity_bytes, byteorder="little") / 10

        return {
            "co2": co2,
            "pressure": pressure,
            "temperature": temperature,
            "humidity": humidity
        }
    except Exception as e:
        print(f"Error decoding advertisement data: {e}")
        return None

def scan_callback(scan_input, air_data):
    """Callback function to process scan results."""
    try:
        scan_result = json.loads(scan_input[0])
        data = scan_result.get("data", "")

        decoded_data = adv_data_decode(data)
        if decoded_data:
            air_data["co2"] = decoded_data["co2"]
            air_data["pressure"] = decoded_data["pressure"]
            air_data["temperature"] = decoded_data["temperature"]
            air_data["humidity"] = decoded_data["humidity"]
    except Exception as e:
        print(f"Error in scan callback: {e}")

def scan_for_air_quality_process(air_data):
    """Runs air quality scan in a separate process to avoid threading issues."""
    try:
        dongle = BleuIO()
        dongle.at_central()
        dongle.register_scan_cb(lambda scan_input: scan_callback(scan_input, air_data))
        dongle.at_findscandata(BOARD_ID, 3)

        # Wait for data to be received (max 10 seconds)
        for _ in range(10):
            if air_data["co2"] > 0:
                return
            time.sleep(1)

    except Exception as e:
        print(f"Error scanning for air quality: {e}")

@app.route('/')
def index():
    """Serve the HTML page."""
    return render_template("index.html")

@app.route('/chat', methods=['POST'])
def chat():
    """Handles user input, fetches air quality data if needed, and returns AI response."""
    user_input = request.json.get("message", "").lower()

    with Manager() as manager:
        air_data = manager.dict({"co2": 0, "pressure": 0, "temperature": 0, "humidity": 0})
        process = Process(target=scan_for_air_quality_process, args=(air_data,))
        process.start()
        process.join()

        # Check for specific sensor queries
        if "temperature" in user_input:
            if air_data["temperature"] > 0:
                response = f"The current temperature in your room is {air_data['temperature']}°C."
            else:
                response = "⚠️ Unable to retrieve temperature data. Ensure HibouAir is in range."
            return jsonify({"response": response})

        elif "humidity" in user_input:
            if air_data["humidity"] > 0:
                response = f"The current humidity level in your room is {air_data['humidity']}%."
            else:
                response = "⚠️ Unable to retrieve humidity data. Ensure HibouAir is in range."
            return jsonify({"response": response})

        elif "pressure" in user_input:
            if air_data["pressure"] > 0:
                response = f"The current air pressure in your room is {air_data['pressure']} hPa."
            else:
                response = "⚠️ Unable to retrieve air pressure data. Ensure HibouAir is in range."
            return jsonify({"response": response})
        elif "co2" in user_input:
            if air_data["co2"] > 0:
                response = f"The current CO2 in your room is {air_data['co2']} ppm."
            else:
                response = "⚠️ Unable to retrieve co2 data. Ensure HibouAir is in range."
            return jsonify({"response": response})

        elif "air quality" in user_input :
            if air_data["co2"] > 0:
                prompt = (
                    f"The current air quality readings are:\n"
                    f"- CO2 Level: {air_data['co2']} ppm\n"
                    f"- Temperature: {air_data['temperature']}°C\n"
                    f"- Humidity: {air_data['humidity']}%\n"
                    f"- Pressure: {air_data['pressure']} hPa\n"
                    f"First give all the data. This is my room data. Give me short analysis on this data. and give me short suggestions "
                )
            else:
                return jsonify({"response": "⚠️ Unable to retrieve air quality data. Ensure HibouAir is in range and try again."})
        else:
            # Normal AI response for non-air quality queries
            prompt = user_input

    ai_response = subprocess.run(
        ["ollama", "run", "gemma", prompt],
        capture_output=True,
        text=True
    ).stdout.strip()

    return jsonify({"response": ai_response})

if __name__ == "__main__":
    app.run(debug=True)
