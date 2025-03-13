import json
import psycopg2
from handlers.account_type import create_account_type, update_account_type, delete_account_type, get_account_types, get_account_type_by_id
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
            if path == "/account_type/create":
                return create_account_type(conn, body, event)
            elif path == "/account_type/update":
                return update_account_type(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/account_type/delete":
                return delete_account_type(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path == "/account_type/all":
                return get_account_types(conn, event)
            elif path.startswith("/account_type/") and path.count("/") == 2:
                return get_account_type_by_id(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
