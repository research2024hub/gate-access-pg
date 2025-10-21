import json
import psycopg2
from handlers.gate import (monitor_heartbeat)
import os
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")
    try:
        conn = psycopg2.connect(db_url)
        result = monitor_heartbeat(conn)
        conn.close()
        return result
    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()