import bcrypt
import jwt
import os
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from utils import _error_response, _success_response, process_db_results, log
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
    if not is_admin:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s
                      AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
                      AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_DEVICES')
                ) AS has_privilege;
            """, (payload.get("user_id"), gate_id))
            result = cur.fetchone()
            if not (result and result["has_privilege"]):
                return _error_response(403, "Not authorized to generate a gate controller token for this estate.")
            
            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            result = cur.fetchone()

            log(conn, "GATE_CONTROLLER_TOKEN_GENERATION", f"Token created for gate '{gate_id}' [{result["name"]}]", user_id, None, result["estate_id"])

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

    # If caller is not a global admin, check estate admin privileges.
    if not is_admin:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s
                      AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
                      AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_DEVICES')
                ) AS has_privilege;
            """, (payload.get("user_id"), gate_id))
            result = cur.fetchone()
            if not (result and result["has_privilege"]):
                return _error_response(403, "Not authorized to generate a tablet token for this estate.")
            
            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            result = cur.fetchone()
            
            log(conn, "TABLET_TOKEN_GENERATION", f"Token created for tablet at gate '{gate_id}' [{result["name"]}]", user_id, None, result["estate_id"])

            conn.commit()
    
    token_payload = {
        "gate_id": gate_id,
        "type": "TABLET"
    }
    
    token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
    
    return _success_response(200, {"tablet_token": token})