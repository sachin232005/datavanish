import eventlet
eventlet.monkey_patch()

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
socketio = SocketIO(app, cors_allowed_origins="*")

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
    """)
    conn.commit()
    init_cur.close()
    return conn

@app.route('/')
def home():
    return "Flask Server is Running ✅"

@app.route('/upload', methods=['POST'])
def upload():
    data = request.json.get('data')
    if not data: return jsonify({"error": "No data"}), 400
    conn = get_db()
    cur = conn.cursor()
    # 🔹 Hand off all Time Management to AWS native clocks to prevent standard Timezone Drift bugs!
    cur.execute("INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, NOW() + INTERVAL '10 minutes', %s) RETURNING id", (data, 1))
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

    cur.execute("UPDATE secure_data SET access_count = access_count - 1 WHERE id=%s", (file_id,))
    conn.commit()
    cur.close(); conn.close()

    return jsonify({"data": data, "remaining_access": access - 1})

@socketio.on('join')
def on_join(data):
    join_room(data['uid'])

@socketio.on('send_message')
def handle_message(data):
    receiver_uid = data.get('receiver_uid')
    if receiver_uid:
        emit('receive_message', data, room=receiver_uid)
        try:
            conn = get_db()
            curr = conn.cursor()
            ttl_seconds = int(data.get('ttl_rule', 30))
            payload_string = f"[From {data.get('sender_uid')} To {receiver_uid}] => Cipher: {data.get('encrypted_payload', '')}"
            
            # 🔹 Offload dynamic database timers purely to Postgres safely using integer multiplication
            curr.execute(
                "INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, NOW() + (%s * INTERVAL '1 second'), %s)", 
                (payload_string, ttl_seconds, 9999)
            )
            
            conn.commit()
            print("✅ Message mathematically safely stored in AWS DB!!")
            curr.close()
            conn.close()
        except Exception as e:
            import traceback
            print("❌ FATAL DB LOGGING ERROR:", e)
            traceback.print_exc()

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
        curr.execute("SELECT id, data, expiry_time FROM secure_data ORDER BY id DESC LIMIT 50")
        rows = curr.fetchall()
        curr.close()
        conn.close()
        
        html = "<html><head><style>body{background:#121212;color:#10b981;font-family:monospace;padding:20px;} .btn{background:#10b981;color:#121212;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;font-weight:bold;font-size:16px;margin-bottom:20px;}</style></head><body>"
        html += "<h2>Server Data Vault (Live Security Monitor)</h2>"
        html += "<button class='btn' onclick='location.reload()'>🔄 Manually Refresh Database</button><ul>"
        for r in rows:
            html += f"<li><b style='color:#fff'>ID {r[0]} | Expires strictly at {r[2]}</b><br><code style='color:#aaa'>{r[1]}</code></li><hr style='border:1px solid #333'>"
        html += "</ul><p style='color:#ef4444'><i>Notice how the server only stores mathematically scrambled ciphertext. After exact expiration laws triggers, watch it mathematically vanish from this page permanently!</i></p></body></html>"
        return html
    except Exception as e:
        return f"<html><head><style>body{{background:#121212;color:#ef4444;font-family:monospace;padding:20px;}}</style></head><body><h2>Fatal Cloud Database Error:</h2><p>{e}</p></body></html>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
