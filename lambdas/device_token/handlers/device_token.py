import bcrypt
import jwt
import os
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges_for_gate
from middleware import verify_token

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")  # Replace with a secure key in production

def generate_gate_controller_token(conn, body, event):
    """
    Generates a token for a gate controller using the provided gate_id.
    Accessible only if:
      - The caller is a global admin (is_admin True in the token), OR
      - The caller is an estate admin (has MANAGE_ALL or MANAGE_DEVICES privilege for the estate
        associated with the gate).
    
    Expects a JSON body with:
        { "gate_id": <gate_id> }
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    gate_id = body.get("gate_id")
    if not gate_id:
        return _error_response(400, "Missing 'gate_id' in request body.")
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    # If caller is not a global admin, check estate admin privileges.
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, payload.get("user_id"), gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_devices():
            return _error_response(403, "Not authorized to generate a gate controller token for this estate.")
            
            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            result = cur.fetchone()

            log(conn, "GATE_CONTROLLER_TOKEN_GENERATION", f"Token created for gate '{gate_id}' [{result['name']}]", user_id, None, result["estate_id"])

            conn.commit()

    token_payload = {
        "gate_id": gate_id,
        "type": "GATE"
    }
    
    token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
    
    return _success_response(200, {"gate_controller_token": token})


def generate_tablet_token(conn, body, event):
    """
    Generates a token for a gate tablet using the provided gate_id.
    Accessible only if:
      - The caller is a global admin (is_admin True in the token), OR
      - The caller is an estate admin (has MANAGE_ALL or MANAGE_DEVICES privilege for the estate
        associated with the gate).
    
    Expects a JSON body with:
        { "gate_id": <gate_id> }
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    gate_id = body.get("gate_id")
    if not gate_id:
        return _error_response(400, "Missing 'gate_id' in request body.")
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_devices():
            return _error_response(403, "Not authorized to generate a tablet token for this estate.")
            
            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            result = cur.fetchone()
            
            log(conn, "TABLET_TOKEN_GENERATION", f"Token created for tablet at gate '{gate_id}' [{result['name']}]", user_id, None, result["estate_id"])

            conn.commit()
    
    token_payload = {
        "gate_id": gate_id,
        "type": "TABLET"
    }
    
    token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
    
    return _success_response(200, {"tablet_token": token})