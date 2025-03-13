import json
import psycopg2
from handlers.event import (
    create_event, update_event, delete_event,
    get_event_details, list_events_by_creator, list_events_by_estate
)
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
            if path == "/event/create":
                return create_event(conn, body, event)
            elif path == "/event/update":
                return update_event(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
            
        elif http_method == "DELETE":
            if path == "/event/delete":
                return delete_event(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
    
        elif http_method == "GET":
            if path.startswith("/event/"):
                path_parts = path.split("/")
                if len(path_parts) == 3:
                    return get_event_details(conn, event)
                elif len(path_parts) == 4 and path_parts[2] == "creator":
                    return list_events_by_creator(conn, event)
                elif len(path_parts) == 4 and path_parts[2] == "estate":
                    return list_events_by_estate(conn, event)
            return _error_response(404, f"Path '{path}' not found.")

        return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
