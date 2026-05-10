from gevent import monkey
monkey.patch_all()
try:
    import psycogreen.gevent
    psycogreen.gevent.patch_psycopg()
except (ImportError, AttributeError):
    print("[WARNING] psycogreen not available or incompatible. Database calls will be synchronous (blocking).")

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
import psycopg2
import os
from datetime import datetime, timedelta
import urllib.request
import json
import random
import smtplib
from email.mime.text import MIMEText
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv() # Load keys from .env if present

# 🔹 OTP Configuration (Provide these in your Environment Variables or .env file)
TWILIO_SID = os.environ.get('TWILIO_SID', 'ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', 'your_auth_token')
TWILIO_PHONE = os.environ.get('TWILIO_PHONE', '+1234567890')

EMAIL_SENDER = os.environ.get('EMAIL_SENDER', 'your_email@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', 'your_app_password') # Use App Password for Gmail
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
try:
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
except ValueError:
    SMTP_PORT = 587

app = Flask(__name__)
app.config['SECRET_KEY'] = 'e2ee_messenger_secret'

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_T3Gy0zKZIDPX@ep-lively-flower-a4ahr0gx-pooler.us-east-1.aws.neon.tech/datavanish_db?sslmode=require')

# 🔹 Thread-Safe Database Generator
def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS secure_data (
            id SERIAL PRIMARY KEY,
            data TEXT,
            expiry_time TIMESTAMP,
            access_count INTEGER,
            sender TEXT,
            receiver TEXT
        );
        
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            email TEXT,
            phone TEXT,
            otp_code TEXT,
            otp_expiry TIMESTAMP,
            push_token TEXT
        );
        
        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            name TEXT,
            creator TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
            username TEXT,
            joined_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# Initialize DB at startup
try:
    init_db()
except Exception as e:
    print(f"[DB-INIT-ERROR] {e}")

@app.route('/')
def home():
    return "Flask Server is Running ✅"

@app.route('/signup', methods=['POST'])
def signup():
    data = request.json or {}
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing fields"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "User created"})
    except psycopg2.IntegrityError:
        return jsonify({"error": "User exists"}), 400
    except Exception as e:
        return jsonify({"error": "Error creating user"}), 400

def send_otp_via_email(email, otp):
    try:
        msg = MIMEText(f"Your Data Vanish OTP code is: {otp}\n\nThis code will expire in 5 minutes.")
        msg['Subject'] = 'Secure Login OTP'
        msg['From'] = EMAIL_SENDER
        msg['To'] = email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[Backend Error] Failed to send email: {e}")
        return False

def send_otp_via_sms(phone, otp):
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=f"Your Data Vanish OTP code is: {otp}. Valid for 5 mins.",
            from_=TWILIO_PHONE,
            to=phone
        )
        return True
    except Exception as e:
        print(f"[Backend Error] Failed to send SMS: {e}")
        return False

@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.json or {}
    identifier = data.get('identifier', '').strip().lower()
    
    if not identifier:
        return jsonify({"error": "Identifier required"}), 400

    # Determine if email or phone
    is_email = '@' in identifier
    
    otp = str(random.randint(100000, 999999))
    expiry = datetime.now() + timedelta(minutes=5)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Check if user exists, if not create a placeholder
        cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s) OR LOWER(phone)=LOWER(%s) OR LOWER(username)=LOWER(%s)", (identifier, identifier, identifier))
        user = cur.fetchone()
        
        if not user:
            # Create user if doesn't exist
            if is_email:
                cur.execute("INSERT INTO users (username, email, otp_code, otp_expiry) VALUES (%s, %s, %s, %s)", (identifier, identifier, otp, expiry))
            else:
                cur.execute("INSERT INTO users (username, phone, otp_code, otp_expiry) VALUES (%s, %s, %s, %s)", (identifier, identifier, otp, expiry))
        else:
            cur.execute("UPDATE users SET otp_code=%s, otp_expiry=%s WHERE id=%s", (otp, expiry, user[0]))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # 🔹 ACTUAL SENDING
        sent_success = False
        method = "none"
        if is_email:
            sent_success = send_otp_via_email(identifier, otp)
            method = "email"
        else:
            sent_success = send_otp_via_sms(identifier, otp)
            method = "phone"
        
        if not sent_success:
            print(f"DEBUG: Failed to send {method} OTP. Sending in debug response for now.")
        
        return jsonify({
            "message": f"OTP sent to your {method} successfully" if sent_success else f"Failed to send OTP to {identifier}, please check logs.",
            "type": method,
            "debug_otp": otp if not sent_success else None # Only return OTP if sending failed for testing
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.json or {}
    identifier = data.get('identifier', '').strip().lower()
    otp = data.get('otp', '').strip()

    if not identifier or not otp:
        return jsonify({"error": "Identifier and OTP required"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT username, otp_code, otp_expiry FROM users WHERE LOWER(email)=LOWER(%s) OR LOWER(phone)=LOWER(%s) OR LOWER(username)=LOWER(%s)", (identifier, identifier, identifier))
        user = cur.fetchone()

        if not user:
            cur.close(); conn.close()
            return jsonify({"error": "User not found"}), 404

        username, stored_otp, expiry = user

        if stored_otp == otp and datetime.now() < expiry:
            # Clear OTP after success
            cur.execute("UPDATE users SET otp_code=NULL, otp_expiry=NULL WHERE LOWER(email)=LOWER(%s) OR LOWER(phone)=LOWER(%s) OR LOWER(username)=LOWER(%s)", (identifier, identifier, identifier))
            conn.commit()
            cur.close(); conn.close()
            return jsonify({"message": "Login success", "uid": username})
        else:
            cur.close(); conn.close()
            return jsonify({"error": "Invalid or expired OTP"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    # 🔹 Accept 'identifier' (username/email/phone) OR legacy 'username' field
    identifier = (data.get('identifier') or data.get('username') or '').strip()
    password = (data.get('password') or '').strip()

    if not identifier or not password:
        return jsonify({"error": "Identifier and password required"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()

        # 🔹 Case-insensitive match against username, email, or phone
        cur.execute("""
            SELECT username, email, phone FROM users 
            WHERE (LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s) OR LOWER(phone)=LOWER(%s)) 
            AND password=%s
        """, (identifier, identifier, identifier, password))
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user:
            return jsonify({
                "message": "Login success",
                "uid": user[0],
                "email": user[1],
                "phone": user[2]
            })
        else:
            return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_token', methods=['POST'])
def update_token():
    data = request.json or {}
    username = data.get('username')
    push_token = data.get('push_token')
    
    if not username or not push_token:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET push_token=%s WHERE LOWER(username)=LOWER(%s)", (push_token, username))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Token updated"})

@app.route('/get_profile/<username>')
def get_profile(username):
    """Fetch the current email and phone for a user to display in the edit profile screen."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, email, phone, password FROM users 
            WHERE LOWER(username) = LOWER(%s)
        """, (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            return jsonify({
                "username": user[0], 
                "email": user[1], 
                "phone": user[2],
                "has_password": user[3] is not None and user[3] != ""
            })
        else:
            return jsonify({"error": "User not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_profile', methods=['POST'])
def update_profile():
    """Allow a user to update their email and/or phone number.
    Requires identifier + current password. If user has no password (OTP signup), 
    the provided password becomes their new password."""
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    new_email = (data.get('email') or '').strip() or None
    new_phone = (data.get('phone') or '').strip() or None
    new_username = (data.get('new_username') or '').strip() or None

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    if not new_email and not new_phone and not new_username:
        return jsonify({"error": "Provide at least one field to update (username, email or phone)"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()

        # 🔹 Fetch current user details including password
        cur.execute("""
            SELECT id, password FROM users 
            WHERE LOWER(username)=LOWER(%s)
        """, (username,))
        user = cur.fetchone()

        if not user:
            cur.close(); conn.close()
            return jsonify({"error": "User not found"}), 404

        user_id, stored_password = user

        # 🔹 Security Check: 
        # 1. If user HAS a password, it MUST match.
        # 2. If user HAS NO password (NULL), we allow them to update AND set this as their new password.
        if stored_password is not None and stored_password != "":
            if stored_password != password:
                cur.close(); conn.close()
                return jsonify({"error": "Unauthorized: invalid password"}), 401
            set_pwd_logic = "" # No need to update password if it already matched
        else:
            # User had no password, so we set the one they just typed as their new password!
            set_pwd_logic = "password=%s,"
            print(f"[Profile] User {username} is setting their first password during profile update.")

        # 🔹 Build update query
        fields = []
        values = []
        
        # If we need to set the first password
        if set_pwd_logic:
            fields.append("password=%s")
            values.append(password)
            
        if new_email:
            fields.append("email=%s")
            values.append(new_email)
        if new_phone:
            fields.append("phone=%s")
            values.append(new_phone)
        if new_username:
            fields.append("username=%s")
            values.append(new_username)

        values.append(user_id)  # WHERE id=
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=%s", values)
        
        if new_username:
            cur.execute("UPDATE secure_data SET sender=%s WHERE LOWER(sender)=LOWER(%s)", (new_username, username))
            cur.execute("UPDATE secure_data SET receiver=%s WHERE LOWER(receiver)=LOWER(%s)", (new_username, username))
            cur.execute("UPDATE group_members SET username=%s WHERE LOWER(username)=LOWER(%s)", (new_username, username))
            cur.execute("UPDATE groups SET creator=%s WHERE LOWER(creator)=LOWER(%s)", (new_username, username))
            
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "Profile updated successfully"})
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Username, email, or phone already in use by another account"}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/conversations/<username>')
def get_conversations(username):
    conn = get_db()
    cur = conn.cursor()

    # 🔹 Auto-vanish naturally expired text data from the cloud
    cur.execute("DELETE FROM secure_data WHERE expiry_time < NOW()")
    conn.commit()

    cur.execute("""
        SELECT 
            sub.user_alias, 
            sub.latest_activity,
            u.email,
            u.phone
        FROM (
            SELECT 
                CASE 
                    WHEN sender = %s THEN receiver 
                    ELSE sender 
                END AS user_alias,
                MAX(expiry_time) as latest_activity
            FROM secure_data
            WHERE sender = %s OR receiver = %s
            GROUP BY user_alias
        ) sub
        LEFT JOIN users u ON LOWER(sub.user_alias) = LOWER(u.username)
    """, (username, username, username))

    rows = cur.fetchall()
    
    result = [{"user": r[0], "latest_activity": r[1], "email": r[2], "phone": r[3]} for r in rows if r[0]]
    
    # 🔹 Fetch groups the user belongs to
    cur.execute("""
        SELECT g.id, g.name, MAX(s.expiry_time)
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        LEFT JOIN secure_data s ON CAST(g.id AS TEXT) = s.receiver
        WHERE LOWER(gm.username) = LOWER(%s)
        GROUP BY g.id, g.name
    """, (username,))
    
    group_rows = cur.fetchall()
    for gr in group_rows:
        result.append({
            "user": f"GROUP:{gr[0]}:{gr[1]}", # Special prefix for groups
            "latest_activity": gr[2],
            "is_group": True
        })

    cur.close()
    conn.close()
    return jsonify(result)

@app.route('/create_group', methods=['POST'])
def create_group():
    data = request.json or {}
    name = data.get('name')
    creator = data.get('creator')
    members = data.get('members', []) # List of usernames

    if not name or not creator:
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO groups (name, creator) VALUES (%s, %s) RETURNING id", (name, creator))
        group_id = cur.fetchone()[0]
        
        # Add creator as member
        if creator not in members:
            members.append(creator)
            
        for member in members:
            cur.execute("INSERT INTO group_members (group_id, username) VALUES (%s, %s)", (group_id, member.strip().lower()))
            
        conn.commit()
        return jsonify({"message": "Group created", "group_id": group_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/resolve_user/<identifier>')
def resolve_user(identifier):
    identifier = identifier.strip().lower()
    conn = get_db()
    cur = conn.cursor()
    # Find the real username associated with this phone or email
    # Find the real username and contact info associated with this ID
    cur.execute("""
        SELECT username, email, phone FROM users 
        WHERE LOWER(email)=LOWER(%s) OR LOWER(phone)=LOWER(%s) OR LOWER(username)=LOWER(%s)
    """, (identifier, identifier, identifier))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        return jsonify({
            "username": user[0],
            "email": user[1],
            "phone": user[2]
        })
    else:
        # Check if it's a group ID
        if identifier.upper().startswith("GROUP:"):
            return jsonify({"username": identifier.upper(), "is_group": True})
        
        # If user doesn't exist yet, return identifier as username
        return jsonify({"username": identifier, "email": None, "phone": None})

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

    # 🔹 Handle Group Messages
    if user2.startswith("GROUP:"):
        group_id = user2.split(":")[1]
        cur.execute("""
            SELECT data, sender, receiver, id FROM secure_data
            WHERE receiver = %s
            ORDER BY id ASC
        """, (group_id,))
    else:
        # 🔹 Handle 1-to-1 Messages
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
    data = request.json or {}
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
    data = request.json or {}
    data_content = data.get('data')
    if not data_content: return jsonify({"error": "No data"}), 400
    conn = get_db()
    cur = conn.cursor()
    # 🔹 Hand off all Time Management to AWS native clocks to prevent standard Timezone Drift bugs!
    # 🔹 Changed from '1 minute' to '24 hours' so offline users have time to fetch their encrypted attachments!
    cur.execute("INSERT INTO secure_data (data, expiry_time, access_count) VALUES (%s, NOW() + INTERVAL '24 hours', %s) RETURNING id", (data_content, 1))
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
        
        # 🔹 If it's a group message, extract just the ID for the database 'receiver' column
        db_receiver = receiver_uid
        if receiver_uid.startswith("GROUP:"):
            db_receiver = receiver_uid.split(":")[1]

        # 🔹 Offload dynamic database timers purely to Postgres safely using integer multiplication
        curr.execute(
            "INSERT INTO secure_data (data, expiry_time, access_count, sender, receiver) VALUES (%s, NOW() + (%s * INTERVAL '1 second'), %s, %s, %s)", 
            (payload, ttl_seconds, 9999, sender_uid, db_receiver)
        )
        
        conn.commit()
        print("[DB] Message mathematically safely stored in AWS DB!!")
        curr.close()
        conn.close()
    except Exception as e:
        import traceback
        print("[DB-ERROR] FATAL DB LOGGING ERROR:", e)
        traceback.print_exc()

@socketio.on('join')
def handle_join(data):
    uid = data.get('uid')
    if uid:
        join_room(uid)
        print(f"[Socket] User {uid} securely joined real-time socket room.")
        
        # 🔹 Also join all group rooms this user belongs to
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT g.id, g.name 
                FROM groups g 
                JOIN group_members gm ON g.id = gm.group_id 
                WHERE LOWER(gm.username) = LOWER(%s)
            """, (uid,))
            groups = cur.fetchall()
            for gid, gname in groups:
                room_name = f"GROUP:{gid}:{gname}"
                join_room(room_name)
                print(f"[Socket] User {uid} joined group room: {room_name}")
            cur.close()
            conn.close()
        except: pass

@socketio.on('send_message')
def handle_message(data):
    receiver_uid = data.get('receiver_uid')
    sender_uid = data.get('sender_uid')
    if receiver_uid:
        emit('receive_message', data, to=receiver_uid)
        
        # Gevent event loops freeze completely when using synchronous C-Extensions like psycopg2.
        # We MUST spin off database inserts directly into a SocketIO background task to prevent client disconnections!
        socketio.start_background_task(
            save_message_to_db, 
            sender_uid, 
            receiver_uid, 
            data.get('encrypted_payload', ''),
            int(data.get('ttl_rule', 30))
        )

        def trigger_push():
            try:
                conn = get_db()
                cur = conn.cursor()
                
                tokens = []
                if receiver_uid.startswith("GROUP:"):
                    gid = receiver_uid.split(":")[1]
                    cur.execute("""
                        SELECT push_token FROM users u 
                        JOIN group_members gm ON u.username = gm.username 
                        WHERE gm.group_id = %s AND LOWER(u.username) != LOWER(%s)
                    """, (gid, sender_uid))
                    tokens = [r[0] for r in cur.fetchall() if r[0]]
                else:
                    cur.execute("SELECT push_token FROM users WHERE username=%s", (receiver_uid,))
                    user_row = cur.fetchone()
                    if user_row and user_row[0]:
                        tokens = [user_row[0]]
                
                cur.close()
                conn.close()
                
                for push_token in tokens:
                    # 🔹 WhatsApp Style: Show Sender Name as Title
                    display_sender = sender_uid.capitalize()
                    message = {
                        'to': push_token,
                        'sound': 'default',
                        'title': f"{display_sender}" if not receiver_uid.startswith("GROUP:") else f"{receiver_uid.split(':')[2]}",
                        'body': f"Sent you a secure message. Tap to decrypt." if not receiver_uid.startswith("GROUP:") else f"{display_sender}: New message",
                        'data': {'sender_uid': sender_uid, 'receiver_uid': receiver_uid} # Deep linking context
                    }
                    req = urllib.request.Request(
                        'https://exp.host/--/api/v2/push/send',
                        data=json.dumps(message).encode('utf-8'),
                        headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
                    )
                    urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                pass
                
        socketio.start_background_task(trigger_push)

@socketio.on('delete_for_everyone')
def handle_delete_everyone(data):
    encrypted_payload = data.get('encrypted_payload')
    receiver_uid = data.get('receiver_uid')
    file_id = data.get('file_id')
    
    if receiver_uid:
        emit('message_deleted', {'encrypted_payload': encrypted_payload}, to=receiver_uid)
        
    def execute_wipe():
        try:
            conn = get_db()
            cur = conn.cursor()
            if encrypted_payload:
                cur.execute("DELETE FROM secure_data WHERE data = %s", (encrypted_payload,))
            if file_id:
                cur.execute("DELETE FROM secure_data WHERE id = %s", (file_id,))
            conn.commit()
            cur.close()
            conn.close()
        except: pass

    socketio.start_background_task(execute_wipe)

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
