# -*- coding: utf-8 -*-
"""Multi-device Python Turbine Telemetry Server with 32-bit int support"""

import os
import secrets
import time
import struct
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
# Safe read wrappers
# -----------------------------
def safe_read(instrument, register, decimals=0):
    try:
        return instrument.read_register(register, decimals)
    except Exception as e:
        print(f"⚠️ Error reading register {register} from {instrument.serial.port}: {e}")
        return None

def safe_read_int32(instrument, register, byteorder="ABCD"):
    """Safely read a 32-bit signed integer from two Modbus registers."""
    try:
        regs = instrument.read_registers(register, 2)  # read 2 registers
        if len(regs) != 2:
            return None

        # Convert to bytes (big endian words)
        raw = regs[0].to_bytes(2, "big") + regs[1].to_bytes(2, "big")

        # Handle word/byte swap
        order_map = {
            "ABCD": raw,
            "CDAB": raw[2:4] + raw[0:2],
            "BADC": raw[1::-1] + raw[3:1:-1],
            "DCBA": raw[::-1],
        }
        raw_ordered = order_map.get(byteorder, raw)

        return int.from_bytes(raw_ordered, byteorder="big", signed=True)

    except Exception as e:
        print(f"⚠️ Error reading 32-bit int register {register} from {instrument.serial.port}: {e}")
        return None

# -----------------------------
# Telemetry generator
# -----------------------------
def generate_telemetry_for_device(name, instrument):
    return {
        'yaw': safe_read(instrument, 100, 2),
        'voltage': safe_read(instrument, 101, 2),
        'current': safe_read(instrument, 102, 2),
        'rpm': safe_read(instrument, 103, 0),
        'windSpeed': safe_read(instrument, 104, 2),
        'windDir': safe_read(instrument, 105, 1),
        # Example 32-bit current value from your ammeter at 0x4000 (16384)
        'dcCurrent': (safe_read_int32(instrument, 0x4000, byteorder="CDAB") or 0) * 0.001
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
