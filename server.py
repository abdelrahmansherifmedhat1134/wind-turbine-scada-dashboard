# -*- coding: utf-8 -*-
"""Wind turbine SCADA server.

Reads the wind direction sensor, DC ammeter and DC voltmeter over Modbus RTU (RS-485) every
second and pushes the readings to the web dashboard (templates/frontendpi.html) with Socket.IO.
Runs on the Raspberry Pi next to the turbine.

Settings come from environment variables (see .env.example):
  SECRET_KEY        Flask secret key (random per start if unset)
  MODBUS_PORT       serial port of the USB-RS485 adapter   (default /dev/ttyUSB0)
  HOST, PORT        address the dashboard listens on        (default 0.0.0.0:5000)
  ALLOWED_ORIGINS   extra origins allowed to open the Socket.IO connection, comma-separated
                    (default: none, so only the dashboard served by this server can connect)
"""

import os
import secrets
import threading
import minimalmodbus
from flask import Flask, render_template
from flask_socketio import SocketIO

# --- Flask & SocketIO Setup ---
# Initialize the web application and SocketIO for real-time communication
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
socketio = SocketIO(app, cors_allowed_origins=allowed_origins or None)   # None = same origin only

# --- Modbus Configuration ---
MODBUS_PORT = os.environ.get("MODBUS_PORT", "/dev/ttyUSB0")

# Attempt to initialize Modbus instruments. If this fails (e.g., USB not connected),
# the server will run in a simulation mode without crashing.
try:
    # Initialize the wind sensor (slave address 1)
    wind_sensor = minimalmodbus.Instrument(MODBUS_PORT, 1)

    # Initialize the ammeter (slave address 2)
    ammeter = minimalmodbus.Instrument(MODBUS_PORT, 2)

    # Initialize the voltmeter (slave address 3)
    voltmeter = minimalmodbus.Instrument(MODBUS_PORT, 3)


    # Configure serial settings for all connected instruments
    for inst in [wind_sensor, ammeter, voltmeter]:
        inst.serial.baudrate = 9600
        inst.serial.timeout = 1
        inst.serial.bytesize = 8
        inst.serial.parity = minimalmodbus.serial.PARITY_NONE
        inst.serial.stopbits = 1

    INSTRUMENTS_AVAILABLE = True
    print("✅ Modbus instruments initialized successfully.")

except Exception as e:
    print(f"🔴 ERROR: Could not initialize Modbus instruments: {e}")
    print("    Server will run in simulation mode. No real data will be read.")
    INSTRUMENTS_AVAILABLE = False
    wind_sensor = None
    ammeter = None
    voltmeter = None


# --- Safe Modbus Reading Functions ---

def safe_read_register(instrument, register, decimals=0):
    """
    Safely reads a 16-bit register from a Modbus device.
    Returns the reading or None if an error occurs.
    """
    if not INSTRUMENTS_AVAILABLE or instrument is None:
        return None
    try:
        # The 'functioncode' argument specifies we are using Function Code 3 (Read Holding Registers)
        return instrument.read_register(register, decimals, functioncode=3)
    except Exception as e:
        print(f"⚠️ Error reading register from slave {instrument.address}: {e}")
        return None

def safe_read_signed_long_big_endian(instrument, register):
    """
    Safely reads a 32-bit signed integer in Big Endian format.
    This is specifically for your ammeter.
    Returns the reading or None if an error occurs.
    """
    if not INSTRUMENTS_AVAILABLE or instrument is None:
        return None
    try:
        # byteorder=0 corresponds to Big-Endian (ABCD) format
        return instrument.read_long(register, signed=True, byteorder=0)
    except Exception as e:
        print(f"⚠️ Error reading signed long from slave {instrument.address}: {e}")
        return None


# --- Background Data Emitter Thread ---
# Global variable to hold the background thread object
background_thread = None
background_thread_lock = threading.Lock()

def modbus_data_emitter():
    """
    Continuously reads data from Modbus devices in a loop and emits it
    to all connected web clients via Socket.IO. This enables real-time updates.
    """
    print("🚀 Starting data emitter thread...")
    while True:
        # --- Read from Wind Sensor (Address 1) ---
        # Reading only Wind Direction from register 0, as requested.
        wind_dir_raw = safe_read_register(wind_sensor, 0, 0)

        # --- Read from Voltmeter (Address 3) ---
        voltage_raw = safe_read_register(voltmeter, 0x0000, 2)

        # --- Read from Ammeter (Address 2) ---
        # Address 0x4000 is 16384 in decimal
        current_raw = safe_read_signed_long_big_endian(ammeter, 16384)

        # --- Process Readings & Handle Disconnections ---
        # If a reading is None, it means the device is likely disconnected.
        # In that case, we send '--' to the frontend.
        wind_dir_val = wind_dir_raw if wind_dir_raw is not None else '--'
        voltage_val = voltage_raw if voltage_raw is not None else '--'

        if current_raw is not None:
            # If the reading is valid, divide by 1000 as requested
            current_val = round(current_raw / 1000.0, 3)
        else:
            # If the reading failed, send '--'
            current_val = '--'

        # --- Placeholder Data for other sensors ---
        # TODO: Replace these with your actual Modbus read calls
        yaw = 155.0
        rpm = 1500.0

        # Determine overall status based on whether all readings were successful
        # Note: We are no longer checking for wind speed.
        all_ok = all(val != '--' for val in [wind_dir_val, voltage_val, current_val])
        status = "OK" if all_ok else "FAULT"


        # --- Prepare and Emit Data Payload ---
        data_payload = {
            'yaw': yaw,
            'volt': voltage_val,
            'amp': current_val,
            'rpm': rpm,
            'status': status,
            'wind_speed': '--', # Sending '--' as we no longer read wind speed
            'wind_dir': wind_dir_val
        }

        print(f"Emitting data: {data_payload}")
        # The `socketio.emit` function sends the data to all connected clients instantly.
        socketio.emit('turbine_update', data_payload)

        # Wait for 1 second before the next read cycle.
        socketio.sleep(1)

# --- Flask & SocketIO Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    # Ensure you have a 'frontendpi.html' file in a 'templates' folder
    return render_template('frontendpi.html')

@socketio.on('connect')
def on_connect():
    """
    This function is triggered when a new client connects to the server.
    It starts the background data-reading thread if it's not already running.
    """
    global background_thread
    print("✅ Client connected to the server.")
    with background_thread_lock:
        if background_thread is None:
            background_thread = socketio.start_background_task(target=modbus_data_emitter)

# --- Main Entry Point ---
if __name__ == '__main__':
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Starting Flask-SocketIO server on http://{host}:{port}")
    socketio.run(app, host=host, port=port)
