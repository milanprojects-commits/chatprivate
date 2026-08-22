from flask import Flask, render_template, request, jsonify, session
from datetime import datetime
import uuid
import sqlite3
import os
import hashlib
import secrets
import smtplib
from email.message import EmailMessage
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'html')
if not os.path.isdir(TEMPLATE_DIR):
    TEMPLATE_DIR = BASE_DIR

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR
)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Database file, stored next to this application so the location does not
# depend on Render's working directory.
DATABASE = os.environ.get(
    'DATABASE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat.db')
)

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

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_code_hash TEXT,
            verification_expires_at INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS saved_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            room_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, room_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (room_id) REFERENCES chat_rooms(room_id)
        )
    ''')
    columns = [row[1] for row in c.execute('PRAGMA table_info(chat_rooms)').fetchall()]
    if 'owner_user_id' not in columns:
        c.execute('ALTER TABLE chat_rooms ADD COLUMN owner_user_id INTEGER')
    conn.commit()
    conn.close()

def get_db():
    """Get database connection"""
    init_db()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def json_error(message, status=400):
    return jsonify({'error': message}), status

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return json_error('Log in first', 401)
        return view(*args, **kwargs)
    return wrapped

def current_user(conn):
    if 'user_id' not in session:
        return None
    return conn.execute('SELECT id, email, username, is_verified FROM users WHERE id = ?',
                        (session['user_id'],)).fetchone()

def make_code():
    return f'{secrets.randbelow(1000000):06d}'

def code_hash(code):
    return hashlib.sha256(code.encode()).hexdigest()

def code_is_valid(row, code):
    return (row and row['verification_code_hash'] == code_hash(code)
            and row['verification_expires_at']
            and row['verification_expires_at'] > int(datetime.now().timestamp()))

def send_code(email, code, subject):
    host = os.environ.get('SMTP_HOST')
    sender = os.environ.get('SMTP_FROM') or os.environ.get('SMTP_USERNAME')
    if not host or not sender:
        app.logger.warning('SMTP is not configured; code for %s is %s', email, code)
        return False
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = email
    message.set_content(f'Your Chatprivate.nl code is: {code}\n\nThis code expires in 15 minutes.')
    with smtplib.SMTP(host, int(os.environ.get('SMTP_PORT', '587'))) as smtp:
        smtp.starttls()
        smtp.login(os.environ.get('SMTP_USERNAME', sender), os.environ.get('SMTP_PASSWORD', ''))
        smtp.send_message(message)
    return True

# Initialize database when the application process starts, before API requests
# can access the tables.
init_db()

@app.route('/')
def home():
    return render_template('first.html')

@app.route('/api/me')
def me():
    conn = get_db()
    user = current_user(conn)
    rooms = []
    if user:
        rooms = [dict(row) for row in conn.execute('''
            SELECT c.room_id, c.name FROM saved_rooms s
            JOIN chat_rooms c ON c.room_id = s.room_id
            WHERE s.user_id = ? ORDER BY s.created_at DESC
        ''', (user['id'],)).fetchall()]
    conn.close()
    return jsonify({'user': dict(user) if user else None, 'rooms': rooms})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not email or '@' not in email or not username or len(username) < 3 or len(password) < 8:
        return json_error('Vul een geldig emailadres, gebruikersnaam en wachtwoord van minimaal 8 tekens in.')
    code = make_code()
    try:
        conn = get_db()
        conn.execute('''INSERT INTO users (email, username, password_hash, verification_code_hash, verification_expires_at)
                        VALUES (?, ?, ?, ?, ?)''', (email, username, generate_password_hash(password), code_hash(code), int(datetime.now().timestamp()) + 900))
        conn.commit()
        conn.close()
        send_code(email, code, 'Chatprivate.nl account verification')
        return jsonify({'status': 'verification_required', 'email': email})
    except sqlite3.IntegrityError:
        return json_error('Dit emailadres of deze gebruikersnaam bestaat al.', 409)
    except Exception:
        app.logger.exception('Registration failed')
        return json_error('De verificatie-email kon niet worden voorbereid.', 500)

@app.route('/api/verify', methods=['POST'])
def verify_account():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (data.get('email', '').strip().lower(),)).fetchone()
    if not code_is_valid(row, data.get('code', '').strip()):
        conn.close()
        return json_error('Ongeldige of verlopen verificatiecode.')
    conn.execute('UPDATE users SET is_verified = 1, verification_code_hash = NULL, verification_expires_at = NULL WHERE id = ?', (row['id'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'verified'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (data.get('email', '').strip().lower(),)).fetchone()
    if not row or not check_password_hash(row['password_hash'], data.get('password', '')):
        conn.close()
        return json_error('Emailadres of wachtwoord is onjuist.', 401)
    if not row['is_verified']:
        conn.close()
        return json_error('Verifieer eerst je account met de code uit je email.', 403)
    session['user_id'] = row['id']
    session['username'] = row['username']
    conn.close()
    return jsonify({'status': 'logged_in', 'username': row['username']})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'logged_out'})

@app.route('/api/forgot/request', methods=['POST'])
def forgot_request():
    email = (request.get_json(silent=True) or {}).get('email', '').strip().lower()
    conn = get_db()
    row = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if row:
        code = make_code()
        conn.execute('UPDATE users SET verification_code_hash = ?, verification_expires_at = ? WHERE id = ?', (code_hash(code), int(datetime.now().timestamp()) + 900, row['id']))
        conn.commit()
        send_code(email, code, 'Chatprivate.nl password reset code')
    conn.close()
    return jsonify({'status': 'code_sent'})

@app.route('/api/forgot/verify', methods=['POST'])
def forgot_verify():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not code_is_valid(row, data.get('code', '').strip()):
        conn.close()
        return json_error('Ongeldige of verlopen herstelcode.')
    new_password = secrets.token_urlsafe(10)
    conn.execute('UPDATE users SET password_hash = ?, verification_code_hash = NULL, verification_expires_at = NULL WHERE id = ?', (generate_password_hash(new_password), row['id']))
    conn.commit()
    conn.close()
    send_code(email, new_password, 'Chatprivate.nl temporary password')
    return jsonify({'status': 'password_sent'})

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
@login_required
def create_server():
    data = request.get_json(silent=True) or {}
    room_name = data.get('name', 'Chat Room')
    password = data.get('password', '')
    username = session['username']
    save_room = bool(data.get('save'))
    
    if not password:
        return jsonify({'error': 'Password required'}), 400
    
    # Create unique room ID
    room_id = str(uuid.uuid4())[:8]
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Insert room
        c.execute('INSERT INTO chat_rooms (room_id, name, password, host, owner_user_id) VALUES (?, ?, ?, ?, ?)',
              (room_id, room_name, password, username, session['user_id']))
        
        # Add host as user
        c.execute('INSERT INTO room_users (room_id, username) VALUES (?, ?)',
                  (room_id, username))
        
        if save_room:
            saved_count = c.execute('SELECT COUNT(*) FROM saved_rooms WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
            if saved_count >= 3:
                conn.rollback()
                conn.close()
                return json_error('Je kunt maximaal 3 rooms opslaan.')
            c.execute('INSERT INTO saved_rooms (user_id, room_id) VALUES (?, ?)', (session['user_id'], room_id))
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
@login_required
def join_server():
    data = request.get_json(silent=True) or {}
    room_id = data.get('room_id')
    password = data.get('password')
    username = session['username']
    save_room = bool(data.get('save'))
    
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

        if save_room:
            saved_count = c.execute('SELECT COUNT(*) FROM saved_rooms WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
            if saved_count >= 3:
                conn.close()
                return json_error('Je kunt maximaal 3 rooms opslaan.')
            c.execute('INSERT OR IGNORE INTO saved_rooms (user_id, room_id) VALUES (?, ?)', (session['user_id'], room_id))
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
@login_required
def send_message():
    data = request.get_json(silent=True) or {}
    room_id = data.get('room_id')
    message = data.get('message')
    username = session['username']
    
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
@login_required
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
@login_required
def send_signal():
    data = request.json or {}
    room_id = data.get('room_id')
    sender = session['username']
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
@login_required
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
