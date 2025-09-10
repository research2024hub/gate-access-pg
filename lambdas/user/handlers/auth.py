import bcrypt
import jwt
import os
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token
import random
import smtplib
from email.mime.text import MIMEText

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key") 
import random

def generate_otp():
    return ''.join(str(random.randint(0, 9)) for _ in range(6))


def send_email_gmail(to_email, subject, message):
    gmail_user = 'vdowana@itconsortiumgh.com'  # e.g. "yourname@gmail.com"
    gmail_app_password = 'rfzlhzhjbdjcqtzj'  # the 16-char app password

    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = gmail_user
    msg['To'] = to_email

    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(gmail_user, gmail_app_password)
    server.send_message(msg)
    server.quit()
    
def create_token(email):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(minutes=15)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def decode_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload["email"]
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except Exception:
        raise ValueError("Invalid token")


def send_user_otp(conn, body):
    email = body.get("email")
    if not email:
        return _error_response(400, "Missing email.")

    otp = generate_otp()
    token = create_token(email)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO pending_users (email, otp, otp_expiry)
            VALUES (%s, %s, NOW() + INTERVAL '10 minutes')
            ON CONFLICT (email) DO UPDATE 
            SET otp = EXCLUDED.otp,
                otp_expiry = EXCLUDED.otp_expiry,
                date_updated = CURRENT_TIMESTAMP
        """, (email, otp))

        conn.commit()
    title = 'Your OTP Code'
    message =f"Your OTP is: {otp}."
    send_email_gmail(email, title, message)

    return _success_response(200, {
        "message": "A new OTP has been sent to your email.",
        "token": token
    })


# def verify_user_otp(conn, body):
#     token = body.get("token")
#     input_otp = body.get("otp")
#     email = decode_token(token)
#     if not input_otp or not token:
#         return _error_response(400, "Missing OTP and token.")

#     with conn.cursor(cursor_factory=RealDictCursor) as cur:
#         cur.execute("""
#             SELECT otp, otp_expiry FROM pending_users
#             WHERE email = %s
#         """, (email,))
#         result = cur.fetchone()

#         if not result:
#             return _error_response(404, "OTP not found.")
#         if result["otp"] != input_otp:
#             return _error_response(401, "Invalid OTP.")
#         if result["otp_expiry"] < datetime.datetime.utcnow():
#             return _error_response(401, "OTP expired.")
#         cur.execute("DELETE FROM pending_users WHERE email = %s", (email,))
#         conn.commit()
#     return _success_response(200, {"message": "OTP verified. Please set your password.","token" : token})

# def register_user(conn, body):
#     """
#     Registers a new user with hashed password.
#     """ 
#     # email = body.get("email")   
#     password = body.get("password")
#     token = body.get("token")
#     email = decode_token(token)

#     if not email or not password:
#         return _error_response(400, "Missing 'email' or 'password'.")

#     hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

#     with conn.cursor(cursor_factory=RealDictCursor) as cur:
#         cur.execute("SELECT id FROM users WHERE email = %s", (email,))
#         if cur.fetchone():
#             return _error_response(409, "User already exists.")

#         cur.execute("""
#             INSERT INTO users (email, password)
#             VALUES (%s, %s)
#             RETURNING id
#         """, (email, hashed_password))
#         user_id = cur.fetchone()["id"]

#         log(conn, "USER_REGISTRATION", f"User '{user_id}' [{email}] registered", user_id, None, None)
        
#         conn.commit()

#     return _success_response(201, {"message": "User registered successfully.", "user_id": user_id})

def register_user(conn, body):
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return _error_response(400, "Missing email or password.")

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    otp = str(random.randint(100000, 999999))

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s LIMIT 1;", (email,))
            if cur.fetchone():
                return _error_response(409, "Email already exist as a user.")
        cur.execute("""
                DELETE FROM pending_users WHERE email = %s
            """,(email,))
        cur.execute("""
            INSERT INTO pending_users (email, password, otp, otp_expiry)
            VALUES (%s, %s, %s, NOW() + INTERVAL '10 minutes')
        """, (email, hashed_password, otp))

        title = 'Your OTP Code'
        message =f"Your OTP is: {otp}\n\nExpires in 10 minutes."
        token = create_token(email)
        send_email_gmail(email, title, message)
      

        conn.commit()

    return _success_response(200, {"message": "OTP sent to email. Please verify to complete registration.", "token": token})

def verify_otp(conn, body):
    token = body.get("token")
    input_otp = body.get("otp")

    if not token or not input_otp:
        return _error_response(400, "Missing token or OTP.")

    email = decode_token(token)
    if not email:
        return _error_response(400, "Invalid token.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT password, otp, otp_expiry FROM pending_users WHERE email = %s
        """, (email,))
        row = cur.fetchone()

        if not row:
            return _error_response(404, "No pending registration found for this email.")
        if row["otp"] != input_otp:
            return _error_response(401, "Invalid OTP.")
        if row["otp_expiry"] < datetime.utcnow():
            return _error_response(401, "OTP expired.")

        # Create user
        cur.execute("""
            INSERT INTO users (email, password)
            VALUES (%s, %s)
            RETURNING id
        """, (email, row["password"]))
        user_id = cur.fetchone()["id"]

        # Clean up
        cur.execute("DELETE FROM pending_users WHERE email = %s", (email,))
        log(conn, "USER_REGISTRATION", f"User '{user_id}' [{email}] registered", user_id, None, None)

        conn.commit()

    return _success_response(201, {"message": "Account verified and created successfully.", "user_id": user_id})


def register_admin_user(conn, body):
    """
    Registers a new user with hashed password.
    """
    email = body.get("email")
    password = body.get("password")
    passkey = body.get("passkey")

    if not email or not password:
        return _error_response(400, "Missing 'email' or 'password'.")
    
    if passkey != "adnwcbwcqweinov":
        return _error_response(400, "Invalid passkey.")

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return _error_response(409, "User already exists.")

        cur.execute("""
            INSERT INTO users (email, password, is_admin)
            VALUES (%s, %s, true)
            RETURNING id
        """, (email, hashed_password))
        user_id = cur.fetchone()["id"]

        log(conn, "GLOBAL_ADMIN_USER_REGISTRATION", f"User '{user_id}' [{email}] registered as global admin", user_id, None, None)
        
        conn.commit()

    return _success_response(201, {"message": "Global Admin User registered successfully.", "user_id": user_id})

def login_user(conn, body):
    """
    Logs in a user and returns a JWT token.
    Debug prints included for all internal values and flow.
    """
    print("\n---[DEBUG] Starting login_user ---")
    email = body.get("email")
    password = body.get("password")

    print("[DEBUG] Received login request. Email:", email)

    if not email or not password:
        print("[DEBUG] Missing email or password in request body")
        return _error_response(400, "Missing 'email' or 'password'.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("[DEBUG] Querying user by email...")
            cur.execute("SELECT id, password, is_active, is_admin FROM users WHERE email = %s", (email,))
            user = cur.fetchone()

            if not user:
                print("[DEBUG] No user found for email:", email)
                return _error_response(401, "Invalid email or password.")

            user_id = user["id"]
            stored_password = user["password"]
            is_active = user["is_active"]
            is_admin = user["is_admin"]

            print(f"[DEBUG] User found: ID={user_id}, is_active={is_active}, is_admin={is_admin}")

            if not bcrypt.checkpw(password.encode("utf-8"), stored_password.encode("utf-8")):
                print("[DEBUG] Password mismatch for user ID:", user_id)
                return _error_response(401, "Invalid email or password.")

            if not is_active:
                print("[DEBUG] Attempted login by deactivated user ID:", user_id)
                return _error_response(403, "User account is deactivated.")

            print("[DEBUG] Password validated. Creating token...")
            token_payload = {
                "user_id": user_id,
                "is_admin": is_admin,
                "exp": datetime.utcnow() + timedelta(hours=24 * 365),  # 1 year token
            }
            token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
            print("[DEBUG] Token generated.")

            print("[DEBUG] Fetching account data for user...")
            cur.execute("""
                SELECT ah.id AS account_holder_id, pi.id AS personal_info_id, ah.user_id, pi.estate_id, pi.name, pi.expiry, pi.contact, es.name AS estate_name, at.name AS account_type_name, ag.name AS access_group_name,
                       ah.house_address, pi.account_type_id, ah.is_active
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN estates es ON pi.estate_id = es.id
                JOIN account_types at ON pi.account_type_id = at.id
                JOIN access_groups ag ON pi.access_group_id = ag.id
                WHERE ah.user_id = %s
            """, (user_id,))

            accounts = cur.fetchall()
            print(f"[DEBUG] Retrieved {len(accounts)} account(s).")

            print("[DEBUG] Logging user login...")
            log(conn, "USER_LOGIN", f"User '{user_id}' [{email}] logged in", user_id, None, None)

        conn.commit()
        print("[DEBUG] Login flow completed successfully. Returning response.")

        return _success_response(200, {
            "message": "Login successful.",
            "token": token,
            "user_id": user_id,
            "accounts": process_db_results(accounts)
        })

    except Exception as e:
        conn.rollback()
        print("[ERROR] Exception during login:", str(e))
        return _error_response(500, "Internal server error during login.")


def change_password(conn, body, event):
    """
    Allows an authenticated user to change their password.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    old_password = body.get("old_password")
    new_password = body.get("new_password")

    if not old_password or not new_password:
        return _error_response(400, "Missing 'old_password' or 'new_password'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT password FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()

        if not row:
            return _error_response(404, "User not found.")

        stored_password = row["password"]
        if not bcrypt.checkpw(old_password.encode("utf-8"), stored_password.encode("utf-8")):
            return _error_response(401, "Old password is incorrect.")

        new_hashed_password = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        cur.execute("""
            UPDATE users SET password = %s
            WHERE id = %s
        """, (new_hashed_password, user_id))

        log(conn, "USER_PASSWORD_CHANGE", f"User '{user_id}' password changed", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Password changed successfully.", "user_id": user_id})
