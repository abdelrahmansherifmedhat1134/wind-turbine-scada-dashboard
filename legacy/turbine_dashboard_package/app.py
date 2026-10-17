from flask import Flask, render_template, request
from flask_socketio import SocketIO
import eventlet

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/update', methods=['POST'])
def update():
    data = request.json
    socketio.emit('telemetry', data)
    return "OK", 200

@socketio.on('connect')
def connected():
    print("Browser connected")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
