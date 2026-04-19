# 🔹 Core Gevent Hack: Force python networking natively into async memory so Gunicorn cloud servers NEVER crash from Socket Timeout!
from gevent import monkey
monkey.patch_all()

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
import psycopg2
import os
from datetime import datetime, timedelta
from flask import send_from_directory

app = Flask(__name__)
app.config['SECRET_KEY'] = 'e2ee_messenger_secret'

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_T3Gy0zKZIDPX@ep-lively-flower-a4ahr0gx-pooler.us-east-1.aws.neon.tech/datavanish_db?sslmode=require')

# 🔹 Thread-Safe Database Generator
# By wrapping the DB connection mathematically into an on-demand function, Gunicorn Boots infinitely fast and bypasses 502 Boot Timeouts completely!
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    init_cur = conn.cursor()
    init_cur.execute("""
        CREATE TABLE IF NOT EXISTS secure_data (
            id SERIAL PRIMARY KEY,
            data TEXT,
            expiry_time TIMESTAMP,
            access_count INTEGER
        );
        
        ALTER TABLE secure_data ADD COLUMN IF NOT EXISTS sender TEXT;
        ALTER TABLE secure_data ADD COLUMN IF NOT EXISTS receiver TEXT;

        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
        );
    """)
    conn.commit()
    init_cur.close()
    return conn

@app.route('/')
def home():
    return "Flask Server is Running ✅"

@app.route('/signup', methods=['POST'])
def signup():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        return jsonify({"message": "User created"})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "User exists"}), 400
    except Exception as e:
        return jsonify({"error": "Error creating user"}), 400
    finally:
        cur.close()
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
    user = cur.fetchone()

    cur.close()
    conn.close()

    if user:
        return jsonify({"message": "Login success", "uid": username})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

@app.route('/conversations/<username>')
def get_conversations(username):
    conn = get_db()
    cur = conn.cursor()

    # 🔹 Auto-vanish naturally expired text data from the cloud
    cur.execute("DELETE FROM secure_data WHERE expiry_time < NOW()")
    conn.commit()

    cur.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN sender = %s THEN receiver 
                ELSE sender 
            END AS user_alias,
            MAX(expiry_time) 
        FROM secure_data
        WHERE sender = %s OR receiver = %s
        GROUP BY user_alias
    """, (username, username, username))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    result = [{"user": r[0], "latest_activity": r[1]} for r in rows if r[0]]
    return jsonify(result)

@app.route('/messages/<user1>/<user2>')
def get_messages(user1, user2):
    conn = get_db()
    cur = conn.cursor()

    # 🔹 Auto-vanish naturally expired text data from the cloud
    cur.execute("DELETE FROM secure_data WHERE expiry_time < NOW()")
    conn.commit()

    # 🔹 [OFFLINE DELIVERY & VANISH ON READ]
    # If the receiver is finally fetching messages that have been sitting offline...
    # We trigger the physical vanishing protocol (30 seconds remaining) exactly when they look at it!
    cur.execute("""
        UPDATE secure_data 
        SET expiry_time = NOW() + INTERVAL '30 seconds'
        WHERE receiver = %s AND sender = %s AND expiry_time > NOW() + INTERVAL '1 minute'
    """, (user1, user2))
    conn.commit()

    cur.execute("""
        SELECT data, sender, receiver, id FROM secure_data
        WHERE (sender = %s AND receiver = %s) OR (sender = %s AND receiver = %s)
        ORDER BY id ASC
    """, (user1, user2, user2, user1))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    result = [{"text": r[0], "sender": r[1], "receiver": r[2], "id": r[3]} for r in rows]
    return jsonify(result)

@app.route('/delete_chat/<user1>/<user2>', methods=['DELETE'])
def delete_chat(user1, user2):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM secure_data 
            WHERE (sender = %s AND receiver = %s) OR (sender = %s AND receiver = %s)
        """, (user1, user2, user2, user1))
        conn.commit()
        return jsonify({"message": "Chat wiped permanently."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/delete_account', methods=['DELETE'])
def delete_account():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        if not cur.fetchone():
            return jsonify({"error": "Unauthorized"}), 401

        cur.execute("DELETE FROM secure_data WHERE sender=%s OR receiver=%s", (username, username))
        cur.execute("DELETE FROM users WHERE username=%s AND password=%s", (username, password))
        conn.commit()
        return jsonify({"message": "Account sanitized and destroyed."}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/upload', methods=['POST'])
def upload():
    data = request.json.get('data')
    if not data: return jsonify({"error": "No data"}), 400
    conn = get_db()
    cur = conn.cursor()
    # 🔹 Hand off all Time Management to AWS native clocks to prevent standard Timezone Drift bugs!
    cur.execute("INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, NOW() + INTERVAL '1 minute', %s) RETURNING id", (data, 1))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id})

@app.route('/data/<int:file_id>', methods=['GET'])
def get_data(file_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT data, expiry_time, access_count FROM secure_data WHERE id=%s", (file_id,))
    row = cur.fetchone()
    
    if not row:
        cur.close(); conn.close()
        return jsonify({"error": "Data not found"}), 404

    data, expiry, access = row

    if datetime.now() > expiry or access <= 0:
        cur.execute("DELETE FROM secure_data WHERE id=%s", (file_id,))
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"error": "Data mathematically vanished forever."}), 403

    # Safely immediately vanish data if it is the final authorized read!
    if access == 1:
        cur.execute("DELETE FROM secure_data WHERE id=%s", (file_id,))
    else:
        cur.execute("UPDATE secure_data SET access_count = access_count - 1 WHERE id=%s", (file_id,))
    
    conn.commit()
    cur.close(); conn.close()

    return jsonify({"data": data, "remaining_access": access - 1})

def save_message_to_db(sender_uid, receiver_uid, payload, ttl_seconds):
    try:
        conn = get_db()
        curr = conn.cursor()
        
        # 🔹 Offload dynamic database timers purely to Postgres safely using integer multiplication
        curr.execute(
            "INSERT INTO secure_data (data, expiry_time, access_count, sender, receiver) VALUES (%s, NOW() + (%s * INTERVAL '1 second'), %s, %s, %s)", 
            (payload, ttl_seconds, 9999, sender_uid, receiver_uid)
        )
        
        conn.commit()
        print("[DB] Message mathematically safely stored in AWS DB!!")
        curr.close()
        conn.close()
    except Exception as e:
        import traceback
        print("[DB-ERROR] FATAL DB LOGGING ERROR:", e)
        traceback.print_exc()

@socketio.on('send_message')
def handle_message(data):
    receiver_uid = data.get('receiver_uid')
    if receiver_uid:
        emit('receive_message', data, room=receiver_uid)
        
        # Gevent event loops freeze completely when using synchronous C-Extensions like psycopg2.
        # We MUST spin off database inserts directly into a SocketIO background task to prevent client disconnections!
        socketio.start_background_task(
            save_message_to_db, 
            data.get('sender_uid'), 
            receiver_uid, 
            data.get('encrypted_payload', ''),
            int(data.get('ttl_rule', 30))
        )

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/view_db')
def view_db():
    try:
        conn = get_db()
        curr = conn.cursor()
        curr.execute("DELETE FROM secure_data WHERE expiry_time < NOW()")
        conn.commit()
        curr.execute("SELECT id, data, expiry_time, sender, receiver FROM secure_data ORDER BY id DESC LIMIT 50")
        rows = curr.fetchall()
        
        curr.execute("SELECT id, username FROM users ORDER BY id DESC LIMIT 50")
        users = curr.fetchall()

        curr.close()
        conn.close()
        
        html = "<html><head><style>body{background:#121212;color:#10b981;font-family:monospace;padding:20px;} .btn{background:#10b981;color:#121212;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;font-weight:bold;font-size:16px;margin-bottom:20px;}</style></head><body>"
        html += "<h2>Server Data Vault (Live Security Monitor)</h2>"
        html += "<button class='btn' onclick='location.reload()'>🔄 Manually Refresh Database</button>"
        
        html += "<h3>Registered Accounts</h3><ul>"
        if len(users) == 0: html += "<li style='color:#888'>No users registered yet.</li>"
        for u in users:
            html += f"<li><b style='color:#3b82f6'>User ID {u[0]} | @{u[1]}</b></li>"
        html += "</ul><hr style='border:1px solid #333'>"

        html += "<h3>Stored Encrypted Payloads</h3><ul>"
        for r in rows:
            html += f"<li><b style='color:#fff'>ID {r[0]} | {r[3] or 'SYS'} &rarr; {r[4] or 'SYS'} | Expires at {r[2]}</b><br><code style='color:#aaa'>{r[1]}</code></li><hr style='border:1px solid #333'>"
        html += "</ul><p style='color:#ef4444'><i>Notice how the server only stores mathematically scrambled ciphertext. After exact expiration laws triggers, watch it mathematically vanish from this page permanently!</i></p></body></html>"
        return html
    except Exception as e:
        return f"<html><head><style>body{{background:#121212;color:#ef4444;font-family:monospace;padding:20px;}}</style></head><body><h2>Fatal Cloud Database Error:</h2><p>{e}</p></body></html>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
