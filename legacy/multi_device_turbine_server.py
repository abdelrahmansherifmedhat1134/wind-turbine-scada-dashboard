# -*- coding: utf-8 -*-
"""Multi-device Python Turbine Telemetry Server"""

import os
import secrets
import time
from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import minimalmodbus

# -----------------------------
# Flask + SocketIO setup
# -----------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*")

# -----------------------------
# Serve dashboard.html
# -----------------------------
@app.route('/')
def index():
    current_dir = os.path.dirname(__file__)
    html_path = os.path.join(current_dir, "dashboard.html")

    if os.path.exists(html_path):
        return send_from_directory(current_dir, "dashboard.html")
    else:
        return send_from_directory(os.path.join(current_dir, "static"), "dashboard.html")

# -----------------------------
# Configure multiple devices
# -----------------------------
devices = {}

def add_device(name, port, slave_address, baudrate=9600, timeout=0.5):
    """Register a Modbus device with a friendly name."""
    try:
        instr = minimalmodbus.Instrument(port, slave_address)
        instr.baudrate = baudrate
        instr.timeout = timeout
        instr.mode = minimalmodbus.MODE_RTU
        devices[name] = instr
        print(f"✅ Added device '{name}' on {port}, addr={slave_address}")
    except Exception as e:
        print(f"⚠️ Failed to configure device '{name}': {e}")

# Example: add multiple devices here
add_device("turbine1", "/dev/ttyUSB0", 1)
add_device("turbine2", "/dev/ttyUSB0", 2)
# add_device("meter1", "/dev/ttyUSB1", 1)

# -----------------------------
# Safe read wrapper
# -----------------------------
def safe_read(instrument, register, decimals=0):
    try:
        return instrument.read_register(register, decimals)
    except Exception as e:
        print(f"⚠️ Error reading register {register} from {instrument.serial.port}: {e}")
        return None

def generate_telemetry_for_device(name, instrument):
    """Read telemetry for one device."""
    return {
        'yaw': safe_read(instrument, 100, 2),
        'voltage': safe_read(instrument, 101, 2),
        'current': safe_read(instrument, 102, 2),
        'rpm': safe_read(instrument, 103, 0),
        'windSpeed': safe_read(instrument, 104, 2),
        'windDir': safe_read(instrument, 105, 1),
    }

# -----------------------------
# Background telemetry loop
# -----------------------------
def background_telemetry_thread():
    while True:
        all_data = {}
        for name, instr in devices.items():
            all_data[name] = generate_telemetry_for_device(name, instr)

        # Emit one big JSON with all devices
        socketio.emit('telemetry', all_data)
        time.sleep(1)

# -----------------------------
# Socket.IO events
# -----------------------------
@socketio.on('connect')
def handle_connect():
    print("✅ A user connected")

@socketio.on('disconnect')
def handle_disconnect():
    print("❌ A user disconnected")

# -----------------------------
# Main entry
# -----------------------------
if __name__ == '__main__':
    socketio.start_background_task(background_telemetry_thread)
    socketio.run(app, port=3000, host='0.0.0.0', debug=False)
