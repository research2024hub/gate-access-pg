import json
import database
from handlers.privilege import create_privilege, update_privilege, delete_privilege, get_privileges, get_privilege_by_id
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
        conn = database.connect(db_url)

        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/privilege/create":
                return create_privilege(conn, body, event)
            elif path == "/privilege/update":
                return update_privilege(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/privilege/delete":
                return delete_privilege(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path == "/privilege/all":
                return get_privileges(conn, event)
            elif path.startswith("/privilege/") and path.count("/") == 2:
                return get_privilege_by_id(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
