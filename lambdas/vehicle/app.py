import json
import psycopg2
import os
from handlers.vehicle import create_vehicle, update_vehicle, delete_vehicle, get_vehicle_details, list_vehicles_by_owner
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")

    try:
        conn = psycopg2.connect(db_url)

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()
        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}

        if http_method == "POST":
            if path == "/vehicle/create":
                return create_vehicle(conn, body, event)
            elif path == "/vehicle/update":
                return update_vehicle(conn, body, event)
        elif http_method == "DELETE":
            if path == "/vehicle/delete":
                return delete_vehicle(conn, body, event)
        elif http_method == "GET":
            if path.startswith("/vehicle/person/"):
                return list_vehicles_by_owner(conn, event)
            elif path.startswith("/vehicle/"):
                return get_vehicle_details(conn, event)

        return _error_response(404, f"Path '{path}' not found.")

    finally:
        if 'conn' in locals():
            conn.close()
