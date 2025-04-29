import json
import psycopg2
from handlers.guest import (
    create_guest_regular, create_associate, update_guest, delete_guest, get_estate_guests,
    get_guest_details, get_account_holder_guests, verify_guest_otp, send_otp
)
import os
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")

    try:
        conn = psycopg2.connect(db_url)

        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/guest/create":
                return create_guest_regular(conn, body, event)
            if path == "/guest/create_associate":
                return create_associate(conn, body, event)
            elif path == "/guest/update":
                return update_guest(conn, body, event)
            elif path == "/guest/verify_otp":
                return verify_guest_otp(conn, body, event)
            elif path == "/guest/send_otp":
                return send_otp(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/guest/delete":
                return delete_guest(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path.startswith("/guest/account_holder/") and path.count("/") == 3:
                return get_account_holder_guests(conn, event)
            elif path.startswith("/guest/estate/") and path.count("/") == 3:
                return get_estate_guests(conn, event)
            elif path.startswith("/guest/") and path.count("/") == 2:
                return get_guest_details(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
