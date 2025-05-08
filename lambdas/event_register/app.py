import json
import psycopg2
from handlers.event_register import register_guest_for_event, list_event_guests, remove_guest_from_event, use_invite_token
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
            if path == "/event_register/create":
                return register_guest_for_event(conn, body, event)
            elif path == "/event_register/invite/use":
                return use_invite_token(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/event_register/delete":
                return remove_guest_from_event(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET" and path.startswith("/event_register/event/"):
            return list_event_guests(conn, event)

        return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()