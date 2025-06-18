import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_gate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    name = body.get("name")
    estate_id = body.get("estate_id")
    opening_time = body.get("opening_time") or None  # Optional
    closing_time = body.get("closing_time") or None  # Optional

    if not name or not estate_id:
        return _error_response(400, "Missing 'name' or 'estate_id'.")

    with conn.cursor() as cur:
        # Check user privileges
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s 
                AND pi.estate_id = %s 
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
            ) AS exists_flag
        """, (user_id, estate_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage gates in this estate")

        # Insert gate with optional opening_time and closing_time
        cur.execute("""
            INSERT INTO gates (name, estate_id, opening_time, closing_time)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (name, estate_id, opening_time, closing_time))

        gate_id = cur.fetchone()[0]

        log(conn, "GATE_CREATION", 
            f"Gate '{gate_id}' [{name}] created with opening_time={opening_time} and closing_time={closing_time}", 
            user_id, None, estate_id)

        conn.commit()

    return _success_response(201, {"message": "Gate created successfully.", "gate_id": gate_id})


def update_gate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("id")
    name = body.get("name")  # Optional
    opening_time = body.get("opening_time")  # Optional
    closing_time = body.get("closing_time")  # Optional

    if not gate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s 
                AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s) 
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
            ) AS exists_flag
        """, (user_id, gate_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage gates")

        cur.execute("""
            UPDATE gates
            SET 
                name = COALESCE(%s, name),
                opening_time = COALESCE(%s, opening_time),
                closing_time = COALESCE(%s, closing_time)
            WHERE id = %s
            RETURNING estate_id, name
        """, (name, opening_time, closing_time, gate_id))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Gate not found.")

        log(conn, "GATE_UPDATE", 
            f"Gate '{gate_id}' updated: name={name}, opening_time={opening_time}, closing_time={closing_time}", 
            user_id, None, result[0])

        conn.commit()

    return _success_response(200, {"message": "Gate updated successfully.", "gate_id": gate_id})

def delete_gate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("id")
    if not gate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
                    ) AS exists_flag
                    """, (user_id, gate_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage gates")
        
        cur.execute("""
            DELETE FROM gates WHERE id = %s RETURNING name, estate_id
        """, (gate_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Gate not found.")
        
        log(conn, "GATE_DELETION", f"Gate '{gate_id}' [{result[0]}] updated", user_id, None, result[1])

        conn.commit()

    return _success_response(200, {"message": "Gate deleted successfully."})

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

def get_gates(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve gates.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, estate_id, date_created, date_updated FROM gates")
        gates = cur.fetchall()

    return _success_response(200, {"gates": process_db_results(gates)})

def get_gates_by_estate(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")
    estate_id = event.get("pathParameters", {}).get("estate_id")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
                    ) AS exists_flag
                    """, (user_id, estate_id))
        
        has_privileges = cur.fetchone()["exists_flag"]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to retrieve gates from this estate")
        
        cur.execute("SELECT id, name, estate_id, date_created, date_updated FROM gates")
        gates = cur.fetchall()

    return _success_response(200, {"gates": process_db_results(gates)})

def get_gate_by_id(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete gates.")

    gate_id = event.get("pathParameters", {}).get("id")
    if not gate_id:
        return _error_response(400, "Missing gate ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, estate_id, date_created, date_updated
            FROM gates WHERE id = %s
        """, (gate_id,))
        gate = cur.fetchone()
        if not gate:
            return _error_response(404, "Gate not found.")

    return _success_response(200, {"gate": process_db_results([gate])})

def get_vehicles_by_gate_no_time_check_by_gate_controller(conn, event):
    """
    Retrieve all vehicles associated with the gate's allowed access groups,
    ignoring time windows.
    """
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized.")

    # Retrieve vehicles from allowed access groups (ignoring time windows)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT v.*
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links
                WHERE gate_id = %s
            );
        """, (gate_id,))
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})

def get_vehicles_by_gate_no_time_check(conn, event):
    """
    Retrieve all vehicles associated with the gate's allowed access groups,
    ignoring time windows.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    
    # Get gate_id from path parameters
    gate_id = event.get("pathParameters", {}).get("gate_id")
    if not gate_id:
        return _error_response(400, "Missing gate id in path parameters.")

    # Check user privileges
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
                  AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
            ) AS exists_flag;
        """, (user_id, gate_id))
        result = cur.fetchone()
        if not (result and (result["exists_flag"] or is_admin)):
            return _error_response(403, "You do not have privileges to view vehicles for this gate.")

        cur.execute("""
            SELECT v.*
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links
                WHERE gate_id = %s
            );
        """, (gate_id,))
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})

def get_vehicles_by_gate_with_time_check_by_gate_controller(conn, event):
    """
    Retrieve vehicles allowed at a gate, considering the gate's time windows.
    This query supports time windows that cross midnight.
    """
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized.")

    # Check user privileges
    with conn.cursor(cursor_factory=RealDictCursor) as cur:

        # Retrieve vehicles with time window check. The time conditions:
        # - If opening_time <= closing_time: current time must be between them.
        # - If opening_time > closing_time: allowed if current time is >= opening_time OR <= closing_time.
        cur.execute("""
            SELECT v.*
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links ga
                JOIN gates g ON g.id = ga.gate_id
                WHERE g.id = %s
                AND (
                    (
                    -- Standard case: opening time <= closing time
                    GREATEST(g.opening_time, ga.opening_time) <= LEAST(g.closing_time, ga.closing_time)
                    AND CURRENT_TIME BETWEEN GREATEST(g.opening_time, ga.opening_time) 
                                        AND LEAST(g.closing_time, ga.closing_time)
                    )
                    OR
                    (
                    -- Crosses midnight: opening > closing
                    GREATEST(g.opening_time, ga.opening_time) > LEAST(g.closing_time, ga.closing_time)
                    AND (CURRENT_TIME >= GREATEST(g.opening_time, ga.opening_time) 
                        OR CURRENT_TIME <= LEAST(g.closing_time, ga.closing_time))
                    )
                )
            );
        """, (gate_id,))
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})

def get_vehicles_by_gate_with_time_check(conn, event):
    """
    Retrieve vehicles allowed at a gate, considering the gate's time windows.
    This query supports time windows that cross midnight.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    
    # Get gate_id from path parameters
    gate_id = event.get("pathParameters", {}).get("gate_id")
    if not gate_id:
        return _error_response(400, "Missing gate id in path parameters.")

    # Check user privileges
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
                  AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GATES')
            ) AS exists_flag;
        """, (user_id, gate_id))
        result = cur.fetchone()
        if not (result and (result["exists_flag"] or is_admin)):
            return _error_response(403, "You do not have privileges to view vehicles for this gate.")

        # Retrieve vehicles with time window check. The time conditions:
        # - If opening_time <= closing_time: current time must be between them.
        # - If opening_time > closing_time: allowed if current time is >= opening_time OR <= closing_time.
        cur.execute("""
            SELECT v.*
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links ga
                JOIN gates g ON g.id = ga.gate_id
                WHERE g.id = %s
                AND (
                    (
                    -- Standard case: opening time <= closing time
                    GREATEST(g.opening_time, ga.opening_time) <= LEAST(g.closing_time, ga.closing_time)
                    AND CURRENT_TIME BETWEEN GREATEST(g.opening_time, ga.opening_time) 
                                        AND LEAST(g.closing_time, ga.closing_time)
                    )
                    OR
                    (
                    -- Crosses midnight: opening > closing
                    GREATEST(g.opening_time, ga.opening_time) > LEAST(g.closing_time, ga.closing_time)
                    AND (CURRENT_TIME >= GREATEST(g.opening_time, ga.opening_time) 
                        OR CURRENT_TIME <= LEAST(g.closing_time, ga.closing_time))
                    )
                )
            );
        """, (gate_id,))
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})

