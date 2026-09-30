import json
import database
from handlers.pedestrian import (
    match_guest_face, save_guest_face, upload_vehicle_image_to_s3
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
        http_method = event.get("httpMethod", "").upper()

        if http_method == "POST":
            if path == "/face/save":
                return save_guest_face(conn, body, event)
            elif path == "/face/match":
                return match_guest_face(conn, body, event)
            elif path == "/face/upload":
                return upload_vehicle_image_to_s3(body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
            
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
