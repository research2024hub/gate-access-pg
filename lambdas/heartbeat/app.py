import json
import psycopg2
from handlers.gate import (monitor_heartbeat,process_messages)
import os
from utils import _error_response as _base_error_response
from middleware import cors_wrap

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

db_url = os.environ.get("DATABASE_URL")
# conn = psycopg2.connect(db_url)
# def lambda_handler(event, context):
#     if not db_url:
#         return _error_response(500, "DATABASE_URL not set")
#     try:
#         conn = psycopg2.connect(db_url)
#         result = monitor_heartbeat(conn)
#         conn.close()
#         return result
#     except Exception as e:
#         return _error_response(500, str(e))
#     finally:
#         if 'conn' in locals():
#             conn.close()


def lambda_handler(event, context):
    path = event.get("path")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")
    conn = psycopg2.connect(db_url)
    try:
        if path == "heartbeat":
            return monitor_heartbeat(conn)
            
        elif path == "message":
            return process_messages(conn)
        else:
            print("Unknown task")
    finally:
        if 'conn' in locals():
            conn.close()
