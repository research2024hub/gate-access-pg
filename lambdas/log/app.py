import json
import psycopg2
from handlers.log import get_logs_by_estate, get_logs_by_account_holder, search_logs_by_account_holder,search_logs_by_estate
import os
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")

    try:
        conn = psycopg2.connect(db_url)

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "GET":
            if path.startswith("/log/estate/"):
                return get_logs_by_estate(conn, event)
            elif path.startswith("/log/account_holder/"):
                return get_logs_by_account_holder(conn, event)
            elif path.startswith("/log/search_account_holder/"):
                return search_logs_by_account_holder(conn, event)
            elif path.startswith("/log/search_estate/"):
                return search_logs_by_estate(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")

        return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
