import json
import psycopg2
from handlers.auth import register_user, verify_otp, send_user_otp, register_admin_user, login_user, change_password
from handlers.user import deactivate_user, activate_user, get_users, get_own_accounts, get_user_accounts, change_user_type,forgot_password,verify_reset_otp,reset_password
import os
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")

    try:
        conn = psycopg2.connect(db_url)
        
        # Ensure body is always a valid dictionary
        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}
        
        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/user/verify_otp":  # Added /user prefix
                return verify_otp(conn, body)
            elif path == "/user/send_otp":  # Added /user prefix
                return send_user_otp(conn, body)
            elif path == "/user/register":  # Added /user prefix
                return register_user(conn, body)
            elif path == "/user/register-admin":  # Added /user prefix
                return register_admin_user(conn, body)
            elif path == "/user/login":  # Added /user prefix
                return login_user(conn, body)
            elif path == "/user/change_password":  # Added /user prefix
                return change_password(conn, body, event)
            elif path == "/user/deactivate":  # Updated (consistent with template.yaml)
                return deactivate_user(conn, body, event)
            elif path == "/user/activate":  # Updated (consistent with template.yaml)
                return activate_user(conn, body, event)
            elif path == "/user/change_type":  # Updated (consistent with template.yaml)
                return change_user_type(conn, body, event)
            elif path == "/user/forgot_password":  # Updated (consistent with template.yaml)
                return forgot_password(conn, body)
            elif path == "/user/verify_reset_otp":  # Updated (consistent with template.yaml)
                return verify_reset_otp(conn, body)
            elif path == "/user/reset_password":  # Updated (consistent with template.yaml)
                return reset_password(conn, body)
            
            else:
                return _error_response(404, f"Path '{path}' not found.")
        if http_method == "GET":
            if path == "/user/all":  # Added /user prefix
                return get_users(conn, event)
            elif path.startswith("/user/accounts/"):
                if path == "/user/accounts/me":
                    return get_own_accounts(conn, event)
                else:
                    return get_user_accounts(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
            
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
