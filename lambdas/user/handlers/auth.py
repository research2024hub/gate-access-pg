import bcrypt
import jwt
import os
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")  # Replace with a secure key in production

def register_user(conn, body):
    """
    Registers a new user with hashed password.
    """
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return _error_response(400, "Missing 'email' or 'password'.")

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return _error_response(409, "User already exists.")

        query = """
            INSERT INTO users (email, password)
            VALUES (%s, %s)
            RETURNING id
        """
        values = [str(email), str(hashed_password)]

        print(f"DEBUG: SQL Query: {query}")
        print(f"DEBUG: SQL Values: {values} (type: {type(values)})")

        cur.execute(query, values)

        user_id = cur.fetchone()["id"]

        print(f"DEBUG: {(email, hashed_password,)}")

        log(conn, "USER_REGISTRATION", f"User '{user_id}' [{email}] registered", user_id, None, None)
        
        conn.commit()

    return _success_response(201, {"message": "User registered successfully.", "user_id": user_id})


def login_user(conn, body):
    """
    Logs in a user and returns a JWT token.
    """
    email = body.get("email")
    password = body.get("password")

    if not email or not password:
        return _error_response(400, "Missing 'email' or 'password'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, password, is_active, is_admin FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if not user:
            return _error_response(401, "Invalid email or password.")

        user_id = user["id"]
        stored_password = user["password"]
        is_active = user["is_active"]
        is_admin = user["is_admin"]

        if not bcrypt.checkpw(password.encode("utf-8"), stored_password.encode("utf-8")):
            return _error_response(401, "Invalid email or password.")

        if not is_active:
            return _error_response(403, "User account is deactivated.")

        token_payload = {
            "user_id": user_id,
            "is_admin": is_admin,
            "exp": datetime.utcnow() + timedelta(hours=24*365),  # Token expires in 2 hours
        }
        token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")

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

        log(conn, "USER_LOGIN", f"User '{user_id}' [{email}] registered", user_id, None, None)

        accounts = cur.fetchall()

    return _success_response(200, {"message": "Login successful.", "token": token, "accounts": process_db_results(accounts)})


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
