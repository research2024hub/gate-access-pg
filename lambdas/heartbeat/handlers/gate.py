import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def update_gate_controller_heartbeat(conn, event):
    """
    Updates the gate's last_controller_heartbeat field to the current timestamp.
    This endpoint should be called by the gate controller to signal its heartbeat.
    """
    # Extract gate_id from path parameters (e.g., /gate/heartbeat/{gate_id})
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized.")

    with conn.cursor() as cur:
        # Check user privileges
        cur.execute("""
            UPDATE gates
            SET last_controller_heartbeat = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING name, estate_id;
        """, (gate_id,))
        row = cur.fetchone()
        if not row:
            return _error_response(404, "Gate not found.")
        
        log(conn, "GATE_CONTROLLER_HEARTBEAT", f"Controller at gate '{gate_id}' [{row[0]}] is alive", None, None, row[1])
        
        conn.commit()

    return _success_response(200, {"message": "Controller heartbeat updated successfully.", "gate_id": gate_id})