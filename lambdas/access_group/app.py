import json
import psycopg2
from handlers.access_group import create_access_group, update_access_group, delete_access_group, get_access_groups, get_access_group_by_id, get_access_groups_by_estate
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

        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/access_group/create":
                return create_access_group(conn, body, event)
            elif path == "/access_group/update":
                return update_access_group(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/access_group/delete":
                return delete_access_group(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path == "/access_group/all":
                return get_access_groups(conn, event)
            elif path.startswith("/access_group/estate/"):
                return get_access_groups_by_estate(conn, event)
            elif path.startswith("/access_group/") and path.count("/") == 2:
                return get_access_group_by_id(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
