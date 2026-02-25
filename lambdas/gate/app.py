import json
import psycopg2
from handlers.gate import (
    create_gate,
    update_gate,
    update_gate_controller_heartbeat,
    delete_gate,
    activate_gate,
    deactivate_gate,
    get_gates,
    get_gate_by_id,
    get_gates_by_estate,
    get_vehicles_by_gate_no_time_check,
    get_vehicles_by_gate_with_time_check,
    get_vehicles_by_gate_no_time_check_by_gate_controller,
    get_vehicles_by_gate_with_time_check_by_gate_controller,
    person_arrives_with_vehicle_callback
)
import os
from handlers.dashboard_handlers import (
    ingest_system_metrics,
    get_latest_system_metrics,
    get_temperature_trend,
    get_camera_downtime,get_storage_trend,get_gate_usage,get_videos
)
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
            if path == "/gate/create":
                return create_gate(conn, body, event)
            elif path == "/gate/update":
                return update_gate(conn, body, event)
            elif path == "/gate/heartbeat":
                return update_gate_controller_heartbeat(conn, event)
            elif path == "/gate/activate":
                return activate_gate(conn, body, event)
            elif path == "/gate/deactivate":
                return deactivate_gate(conn, body, event)
            elif path == "/system/metrics":
                return ingest_system_metrics(conn, body, event)
            elif path.startswith("/gate/vehicle_arrival/callback"):
                return person_arrives_with_vehicle_callback(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/gate/delete":
                return delete_gate(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "GET":
            if path == "/gate/all":
                return get_gates(conn, event)
            elif path.startswith("/gate/controller/vehicles"):
                return get_vehicles_by_gate_no_time_check_by_gate_controller(conn, event)
            elif path.startswith("/gate/controller/timed_vehicles"):
                return get_vehicles_by_gate_with_time_check_by_gate_controller(conn, event)
            elif path.startswith("/gate/estate/") and path.count("/") == 3:
                return get_gates_by_estate(conn, event)
            elif path.startswith("/gate/vehicles/") and path.count("/") == 3:
                return get_vehicles_by_gate_no_time_check(conn, event)
            elif path.startswith("/gate/timed_vehicles/") and path.count("/") == 3:
                return get_vehicles_by_gate_with_time_check(conn, event)
            elif path == "/system/latest_metrics":
                return get_latest_system_metrics(conn, event)
            elif path == "/system/temperature":
                return get_temperature_trend(conn, event)
            elif path == "/cameras/downtime":
                return get_camera_downtime(conn, event)
            elif path == "/system/storage":
                return get_storage_trend(conn, event)
            elif path == "/system/access":
                return get_gate_usage(conn, event)
            elif path == "/system/videos":
                return get_videos(event)
            elif path.startswith("/gate/") and path.count("/") == 2:
                return get_gate_by_id(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
