# -*- coding: utf-8 -*-
"""Turbine Telemetry Server (Voltage + Current only)"""

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
# Configure devices
# -----------------------------
devices = {}

def add_device(name, port, slave_address, baudrate=9600, timeout=0.5):
    """Register a Modbus device."""
    try:
        instr = minimalmodbus.Instrument(port, slave_address)
        instr.baudrate = baudrate
        instr.timeout = timeout
        instr.mode = minimalmodbus.MODE_RTU
        devices[name] = instr
        print(f"✅ Added device '{name}' on {port}, addr={slave_address}")
    except Exception as e:
        print(f"⚠️ Failed to configure device '{name}': {e}")

# Example: edit these for your actual setup
add_device("ammeter", "/dev/ttyUSB0", 1)
add_device("voltmeter", "/dev/ttyUSB0", 2)

# -----------------------------
# Safe read helpers
# -----------------------------
def safe_read(instrument, register, decimals=0):
    try:
        return instrument.read_register(register, decimals)
    except Exception as e:
        print(f"⚠️ Error reading register {register} from {instrument.serial.port}: {e}")
        return None

def safe_read_int32(instrument, register, byteorder="ABCD"):
    try:
        regs = instrument.read_registers(register, 2)
        if len(regs) != 2:
            return None

        raw = regs[0].to_bytes(2, "big") + regs[1].to_bytes(2, "big")
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
def generate_turbine_telemetry():
    """Get only Voltage + Current from the meters."""
    ammeter = devices.get("ammeter")
    voltmeter = devices.get("voltmeter")

    current = (safe_read_int32(ammeter, 0x4000, "CDAB") or 0) * 0.001
    voltage = safe_read(voltmeter, 0x3000, 2)  # ⚠️ replace 0x3000 with voltmeter's actual register

    return {
        "voltage": voltage,
        "current": current
    }

# -----------------------------
# Background telemetry loop
# -----------------------------
def background_telemetry_thread():
    while True:
        data = generate_turbine_telemetry()
        socketio.emit("telemetry", {"turbine1": data})
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
