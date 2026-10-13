import database
from handlers.gate import monitor_heartbeat
import os
from utils import _error_response as _base_error_response
from middleware import cors_wrap


def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))


def lambda_handler(event, context):
    path = event.get("path")
    if path is None and event.get("source") == "aws.events" and event.get("detail-type") == "Scheduled Event":
        path = "heartbeat"
    if isinstance(path, str):
        path = path.strip("/")
    if path == "message":
        return _error_response(501, "Message processing is disabled.")
    if path != "heartbeat":
        return _error_response(400, "Unknown heartbeat task.")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")
    conn = None
    try:
        conn = database.connect(db_url)
        return monitor_heartbeat(conn)
    except Exception:
        if conn is not None:
            conn.rollback()
        return _error_response(500, "Heartbeat execution failed.")
    finally:
        if conn is not None:
            conn.close()
