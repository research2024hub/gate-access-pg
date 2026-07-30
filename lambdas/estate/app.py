import json
import psycopg2
from handlers.estate import create_estate, update_estate, delete_estate, get_estates, get_estate_by_id
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
            if path == "/estate/create":
                return create_estate(conn, body, event)
            elif path == "/estate/update":
                return update_estate(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/estate/delete":
                return delete_estate(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        if http_method == "GET":
            if path == "/estate/all":
                return get_estates(conn, event)
            elif path.startswith("/estate/") and path.count("/") == 2:  # Ensure correct format for /estate/{id}
                return get_estate_by_id(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")

        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
