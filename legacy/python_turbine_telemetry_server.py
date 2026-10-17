# -*- coding: utf-8 -*-
"""Python Turbine Telemetry Server

"""

import os
import secrets
import threading
import time
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

# Import the minimalmodbus library
try:
    import minimalmodbus
except ImportError:
    print("Minimalmodbus library not found. Please install it with 'pip install minimalmodbus'")
    exit()

# Create the Flask app and SocketIO instance
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY") or secrets.token_hex(32) # A secret key is required for sessions
socketio = SocketIO(app, cors_allowed_origins="*") # Allow all origins for simplicity

# Path to the HTML file
html_file_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')

# Serve the static HTML file
@app.route('/')
def index():
    # Use send_from_directory to serve the dashboard.html file
    return send_from_directory(os.path.dirname(__file__), 'dashboard.html')

# Configure your Modbus instrument. Replace these with your device's details.
# Example: Instrument on a USB-to-RS485 converter at /dev/ttyUSB0 with slave address 1
try:
    # Adjust the port, slave address, baudrate, etc., to match your setup.
    instrument = minimalmodbus.Instrument('/dev/ttyUSB0', 1)  # port name, slave address
    instrument.baudrate = 9600
    instrument.timeout = 0.5
    print("Modbus instrument configured successfully.")
except Exception as e:
    print(f"Failed to configure Modbus instrument: {e}")
    instrument = None

# Function to read real sensor data from the Modbus device.
def generate_telemetry_data():
    """Reads real sensor data from the Modbus device and returns it."""

    if not instrument:
        print("Modbus instrument is not available. Returning placeholder data.")
        return {
            'yaw': None,
            'voltage': None,
            'current': None,
            'rpm': None,
            'windSpeed': None,
            'windDir': None,
        }

    try:
        # Replace these register numbers with the actual register addresses
        # from your sensor's documentation.
        # Example: read a holding register at address 100 with 2 decimals
        yaw_value = instrument.read_register(100, 2)
        voltage_value = instrument.read_register(101, 2)
        current_value = instrument.read_register(102, 2)
        rpm_value = instrument.read_register(103, 0) # Assumes RPM is an integer
        wind_speed_value = instrument.read_register(104, 2)
        wind_dir_value = instrument.read_register(105, 1)

    except Exception as e:
        # Handle any errors that occur during sensor reading
        print(f"Error reading from Modbus instrument: {e}")
        # Return default or error values
        return {
            'yaw': None,
            'voltage': None,
            'current': None,
            'rpm': None,
            'windSpeed': None,
            'windDir': None,
        }

    # Return the data as a dictionary. The keys must match the keys used on the frontend.
    return {
        'yaw': yaw_value,
        'voltage': voltage_value,
        'current': current_value,
        'rpm': rpm_value,
        'windSpeed': wind_speed_value,
        'windDir': wind_dir_value,
    }

# This function runs in a separate thread and emits data
def background_telemetry_thread():
    """Emits sensor data to all connected clients."""
    while True:
        data = generate_telemetry_data()
        socketio.emit('telemetry', data)
        # You can uncomment the line below to see the data being emitted
        # print(f"Emitting data: {data}")
        time.sleep(1) # Wait for 1 second

# Handle Socket.IO connections
@socketio.on('connect')
def handle_connect():
    """Handles new client connections."""
    print("A user connected")

@socketio.on('disconnect')
def handle_disconnect():
    """Handles client disconnections."""
    print("A user disconnected")

# Start the background thread when the server starts
if __name__ == '__main__':
    # Start the background thread for emitting telemetry data
    telemetry_thread = threading.Thread(target=background_telemetry_thread)
    telemetry_thread.daemon = True # Daemon threads are terminated when the main program exits
    telemetry_thread.start()

    # Run the SocketIO server on port 3000
    socketio.run(app, port=3000, host='0.0.0.0', debug=False)