from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room  # type: ignore
import psycopg2
import os
from datetime import datetime, timedelta
from flask import send_from_directory

# ✅ FIRST create app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'e2ee_messenger_secret'

# ✅ THEN apply CORS
CORS(app)

# 🔹 Configure SocketIO for real-time Live Chat
socketio = SocketIO(app, cors_allowed_origins="*")

# 🔹 Production PostgreSQL Connection (Supports Localhost OR Cloud Databases automatically!)
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_T3Gy0zKZIDPX@ep-lively-flower-a4ahr0gx-pooler.us-east-1.aws.neon.tech/datavanish_db?sslmode=require')
conn = psycopg2.connect(DATABASE_URL)

# 🔹 AUTO-INITIALIZATION: Automatically construct the missing Neon Database Tables mathematically so we NEVER get a 500 Crash Error!
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

cur = conn.cursor()


# 🔹 Home Route (Fix for "Not Found")
@app.route('/')
def home():
    return "Flask Server is Running ✅"

@app.route('/upload', methods=['POST'])
def upload():
    data = request.json.get('data')

    if not data:
        return jsonify({"error": "No data"}), 400

    expiry = datetime.now() + timedelta(minutes=10)
    access = 1

    cur.execute(
        "INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, %s, %s) RETURNING id",
        (data, expiry, access)
    )

    new_id = cur.fetchone()[0]  # ✅ GET ID

    conn.commit()

    return jsonify({"id": new_id})  # ✅ RETURN ID


# 🔹 Fetch API
@app.route('/data/<int:file_id>', methods=['GET'])
def get_data(file_id):
    cur.execute(
        "SELECT data, expiry_time, access_count FROM secure_data WHERE id=%s",
        (file_id,)
    )
    row = cur.fetchone()

    if not row:
        return jsonify({"error": "Data not found"}), 404

    data, expiry, access = row

    # 🔥 Check expiry
    if datetime.now() > expiry:
        delete_data(file_id)
        return jsonify({"error": "Data expired and deleted"}), 403

    # 🔥 Check access count
    if access <= 0:
        delete_data(file_id)
        return jsonify({"error": "Access limit reached"}), 403

    # 🔻 Decrease access count
    cur.execute(
        "UPDATE secure_data SET access_count = access_count - 1 WHERE id=%s",
        (file_id,)
    )
    conn.commit()

    return jsonify({
        "data": data,
        "remaining_access": access - 1
    })


# 🔹 Delete Function (Self-Destruct)
def delete_data(file_id):
    cur.execute("DELETE FROM secure_data WHERE id=%s", (file_id,))
    conn.commit()


# -----------------------------
# 🔹 Real-Time WebSocket Routes
# -----------------------------

@socketio.on('join')
def on_join(data):
    """Client joins their personal chat room using their public UID"""
    uid = data.get('uid')
    if uid:
        join_room(uid)
        print(f"🔒 Secure Socket Connected: User {uid} joined.")

@socketio.on('send_message')
def handle_message(data):
    """
    Blindly relays the E2EE encrypted payload to the receiver.
    The Server cannot read this data.
    """
    receiver_uid = data.get('receiver_uid')
    if receiver_uid:
        emit('receive_message', data, room=receiver_uid)
        print(f"📡 E2E Payload relayed securely to {receiver_uid}")
        
        # 🔹 Dynamically calculate the precise Expiry Time based on the User's rule!
        try:
            curr = conn.cursor()
            ttl_seconds = int(data.get('ttl_rule', 30)) # Fallback to 30s if not provided
            expiry = datetime.now() + timedelta(seconds=ttl_seconds)
            payload_string = f"[From {data.get('sender_uid')} To {receiver_uid}] => Cipher: {data.get('encrypted_payload', '')}"
            curr.execute(
                "INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, %s, %s)",
                (payload_string, expiry, 9999)
            )
            conn.commit()
            curr.close()
        except Exception as e:
            print("DB logging error:", e)
            conn.rollback()

# 🔹 Route to silence favicon 404 warnings in the console
@app.route('/favicon.ico')
def favicon():
    return '', 204

# 🔹 Admin Route to physically View the Encrypted Server Data for Project Demonstrations
@app.route('/view_db')
def view_db():
    curr = conn.cursor()
    
    # 🔥 1. THE DATA VANISH PURGE: Automatically delete any row that has passed its 30-second expiry timer!
    curr.execute("DELETE FROM secure_data WHERE expiry_time < NOW()")
    conn.commit()

    # 🔥 2. Now fetch whatever active messages are remaining!
    curr.execute("SELECT id, data, expiry_time FROM secure_data ORDER BY id DESC LIMIT 50")
    rows = curr.fetchall()
    curr.close()
    
    # 🔹 Add a 2-second Auto-Refresh Header so the user can just sit back and watch the DB purge itself live on a monitor!
    html = "<html><head><meta http-equiv='refresh' content='2'><style>body{background:#121212;color:#10b981;font-family:monospace;padding:20px;}</style></head><body>"
    html += "<h2>Server Data Vault (Live Auto-Updating every 2 seconds...)</h2><ul>"
    for r in rows:
        html += f"<li><b style='color:#fff'>ID {r[0]} | Expires strictly at {r[2]}</b><br><code style='color:#aaa'>{r[1]}</code></li><hr style='border:1px solid #333'>"
    html += "</ul><p style='color:#ef4444'><i>Notice how the server only stores mathematically scrambled ciphertext. After 30 seconds, watch it vanish from this page permanently!</i></p></body></html>"
    return html

# 🔹 Run Flask + SocketIO Production App
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
