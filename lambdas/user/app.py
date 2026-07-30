import json
import psycopg2
from handlers.auth import register_user, verify_otp, send_user_otp, register_admin_user, login_user, change_password, sendemail, googleauth
from handlers.user import deactivate_user, activate_user, get_users, get_own_accounts, get_user_accounts, change_user_type, forgot_password, verify_reset_otp, reset_password, delete_user, submit_report, get_reports, update_report_status, get_report_status
import os
from utils import _error_response as _base_error_response
from middleware import cors_wrap

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

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
            # elif path == "/user/receive_otp":  # Added /user prefix
            #     return receive_otp(conn, body)
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
                return verify_reset_otp(conn, body, event)
            elif path == "/user/reset_password":  # Updated (consistent with template.yaml)
                return reset_password(conn, body, event)
            elif path == "/user/delete_user":  # Updated (consistent with template.yaml)
                return delete_user(conn, body, event)
            elif path == "/user/emailtest":  # Updated (consistent with template.yaml)
                return sendemail(body)
            elif path == "/user/oauth":  # Updated (consistent with template.yaml)
                return googleauth(body)
            elif path == "/user/submit_report":
                return submit_report(conn, body, event)
            elif path == "/user/update_report_status":
                return update_report_status(conn, body, event)

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
            elif path == "/user/reports":
                return get_reports(conn, event)
            elif path.startswith("/user/report_status/") or path == "/user/report_status":
                return get_report_status(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
            
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
