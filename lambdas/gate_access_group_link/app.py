import json
import database
from handlers.gate_access_group_link import (
    create_access_group_link, remove_access_group_link,
    list_gate_access_groups, list_access_group_gates, update_access_group_link
)
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
        print("path is:",path)
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/gate_access_group_link/create":
                return create_access_group_link(conn, body, event)
            elif path == "/gate_access_group_link/update":
                return update_access_group_link(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/gate_access_group_link/remove":
                return remove_access_group_link(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path.startswith("/gate_access_group_link/gate/"):
                return list_gate_access_groups(conn, event)
            elif path.startswith("/gate_access_group_link/access_group/"):
                return list_access_group_gates(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
