from flask import Flask, render_template, request, jsonify
from datetime import datetime
import uuid
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'html')
if not os.path.isdir(TEMPLATE_DIR):
    TEMPLATE_DIR = BASE_DIR

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR
)
app.secret_key = 'your-secret-key-change-this'

# Database file, stored next to this application so the location does not
# depend on Render's working directory.
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat.db')

def init_db():
    """Initialize database with tables"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Keep schema creation safe when the database already exists but is empty
    # or was created by an older deployment.
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_rooms (
            room_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            password TEXT NOT NULL,
            host TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS room_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            username TEXT NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES chat_rooms(room_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES chat_rooms(room_id)
        )
    ''')
        
    c.execute('''
        CREATE TABLE IF NOT EXISTS call_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    """Get database connection"""
    init_db()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database when the application process starts, before API requests
# can access the tables.
init_db()

@app.route('/')
def home():
    return render_template('first.html')

@app.route('/rtc-config')
def rtc_config():
    ice_servers = [{'urls': 'stun:stun.l.google.com:19302'}]
    turn_url = os.environ.get('TURN_URL', '')
    if turn_url:
        ice_servers.append({
            'urls': turn_url,
            'username': os.environ.get('TURN_USERNAME', ''),
            'credential': os.environ.get('TURN_PASSWORD', '')
        })
    return jsonify({'iceServers': ice_servers})

@app.route('/create-server', methods=['POST'])
def create_server():
    data = request.get_json(silent=True) or {}
    room_name = data.get('name', 'Chat Room')
    password = data.get('password', '')
    username = data.get('username', 'Host')
    
    if not password:
        return jsonify({'error': 'Password required'}), 400
    
    # Create unique room ID
    room_id = str(uuid.uuid4())[:8]
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Insert room
        c.execute('INSERT INTO chat_rooms (room_id, name, password, host) VALUES (?, ?, ?, ?)',
                  (room_id, room_name, password, username))
        
        # Add host as user
        c.execute('INSERT INTO room_users (room_id, username) VALUES (?, ?)',
                  (room_id, username))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'Chat room created!',
            'room_id': room_id,
            'room_name': room_name
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/join-server', methods=['POST'])
def join_server():
    data = request.get_json(silent=True) or {}
    room_id = data.get('room_id')
    password = data.get('password')
    username = data.get('username', 'User')
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check if room exists and password is correct
        c.execute('SELECT * FROM chat_rooms WHERE room_id = ?', (room_id,))
        room = c.fetchone()
        
        if not room:
            conn.close()
            return jsonify({'error': 'Room not found'}), 404
        
        if room['password'] != password:
            conn.close()
            return jsonify({'error': 'Wrong password'}), 401
        
        # Check if user already in room
        c.execute('SELECT * FROM room_users WHERE room_id = ? AND username = ?', 
                  (room_id, username))
        existing_user = c.fetchone()
        
        if not existing_user:
            # Add user to room
            c.execute('INSERT INTO room_users (room_id, username) VALUES (?, ?)',
                      (room_id, username))
            
            # Add system message
            c.execute('INSERT INTO messages (room_id, username, message) VALUES (?, ?, ?)',
                      (room_id, 'System', f'{username} joined the chat'))
        
        conn.commit()
        
        # Get all users in room
        c.execute('SELECT DISTINCT username FROM room_users WHERE room_id = ?', (room_id,))
        users = [row['username'] for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'status': 'Joined successfully',
            'room_id': room_id,
            'room_name': room['name'],
            'users': users
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send-message', methods=['POST'])
def send_message():
    data = request.get_json(silent=True) or {}
    room_id = data.get('room_id')
    message = data.get('message')
    username = data.get('username', 'Anonymous')
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check if room exists
        c.execute('SELECT * FROM chat_rooms WHERE room_id = ?', (room_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Room not found'}), 404
        
        # Insert message
        c.execute('INSERT INTO messages (room_id, username, message) VALUES (?, ?, ?)',
                  (room_id, username, message))
        
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'Message sent'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get-messages', methods=['GET'])
def get_messages():
    room_id = request.args.get('room_id')
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check if room exists
        c.execute('SELECT * FROM chat_rooms WHERE room_id = ?', (room_id,))
        room = c.fetchone()
        
        if not room:
            conn.close()
            return jsonify({'error': 'Room not found'}), 404
        
        # Get all messages
        c.execute('SELECT username, message, strftime("%H:%M:%S", timestamp) as timestamp FROM messages WHERE room_id = ? ORDER BY timestamp ASC',
                  (room_id,))
        messages = [dict(row) for row in c.fetchall()]
        
        # Get all users
        c.execute('SELECT DISTINCT username FROM room_users WHERE room_id = ?', (room_id,))
        users = [row['username'] for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'messages': messages,
            'users': users,
            'room_name': room['name']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send-signal', methods=['POST'])
def send_signal():
    data = request.json or {}
    room_id = data.get('room_id')
    sender = data.get('sender')
    recipient = data.get('recipient')
    signal_type = data.get('type')
    payload = data.get('payload')

    if not all([room_id, sender, recipient, signal_type, payload]):
        return jsonify({'error': 'Incomplete call signal'}), 400

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'SELECT COUNT(*) FROM room_users WHERE room_id = ? AND username IN (?, ?)',
            (room_id, sender, recipient)
        )
        if c.fetchone()[0] != 2:
            conn.close()
            return jsonify({'error': 'Both users must be in the room'}), 403

        c.execute(
            'INSERT INTO call_signals (room_id, sender, recipient, signal_type, payload) VALUES (?, ?, ?, ?, ?)',
            (room_id, sender, recipient, signal_type, payload)
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'Signal sent'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get-signals', methods=['GET'])
def get_signals():
    room_id = request.args.get('room_id')
    recipient = request.args.get('recipient')
    after_id = request.args.get('after_id', 0, type=int)

    if not room_id or not recipient:
        return jsonify({'error': 'Room and recipient are required'}), 400

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT id, sender, signal_type, payload
            FROM call_signals
            WHERE room_id = ? AND recipient = ? AND id > ?
            ORDER BY id ASC
        ''', (room_id, recipient, after_id))
        signals = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({'signals': signals})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=False
    )

