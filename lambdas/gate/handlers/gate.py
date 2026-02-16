import json
from psycopg2.extras import RealDictCursor
from datetime import datetime

from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, log, get_user_privileges_for_estate, get_user_privileges_for_gate, notify_user
from middleware import verify_token, cors_wrap

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))


def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message)) 

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to manage gates in this estate")

        # Insert gate with optional opening_time and closing_time
        if (opening_time and closing_time):
            cur.execute("""
                INSERT INTO gates (name, estate_id, opening_time, closing_time)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (name, estate_id, opening_time, closing_time))
        else:
            cur.execute("""
                INSERT INTO gates (name, estate_id)
                VALUES (%s, %s)
                RETURNING id
            """, (name, estate_id))

        gate_id = cur.fetchone()["id"]

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
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
            user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Gate updated successfully.", "gate_id": gate_id})


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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
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

        log(conn, "GATE_CONTROLLER_HEARTBEAT", f"Controller at gate '{gate_id}' [{row['name']}] is alive", None, None, row["estate_id"])
        
        conn.commit()

    return _success_response(200, {"message": "Controller heartbeat updated successfully.", "gate_id": gate_id})

def delete_gate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("id")
    if not gate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to manage gates")

        cur.execute("""
            DELETE FROM gates WHERE id = %s RETURNING name, estate_id
        """, (gate_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Gate not found.")

        log(conn, "GATE_DELETION", f"Gate '{gate_id}' [{result['name']}] updated", user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Gate deleted successfully."})


def get_gates(conn, event):
    """
    Retrieves all gates with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    Only admins are allowed to perform this action.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve gates.")

    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError
    except ValueError:
        return _error_response(400, "Invalid 'page' or 'page_size' parameter.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM gates")
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT id, name, estate_id, active, last_controller_heartbeat, date_created, date_updated
            FROM gates
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))
        gates = cur.fetchall()

    return _success_response(200, {
        "gates": process_db_results(gates),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

def get_gates_by_estate(conn, event):
    """
    Retrieves all gates for a specific estate with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    Only estate admins or global admins can access this.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")
    estate_id = event.get("pathParameters", {}).get("estate_id")

    if not estate_id:
        return _error_response(400, "Missing 'estate_id' in path parameters.")

    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError
    except ValueError:
        return _error_response(400, "Invalid 'page' or 'page_size' parameter.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to retrieve gates from this estate.")

        # Count total for pagination
        cur.execute("SELECT COUNT(*) FROM gates WHERE estate_id = %s", (estate_id,))
        total = cur.fetchone()["count"]

        # Retrieve paginated gates
        cur.execute("""
            SELECT id, name, estate_id, active, last_controller_heartbeat, date_created, date_updated
            FROM gates
            WHERE estate_id = %s
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (estate_id, page_size, offset))
        gates = cur.fetchall()

    return _success_response(200, {
        "gates": process_db_results(gates),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def get_gate_by_id(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    
    gate_id = event.get("pathParameters", {}).get("id")
    if not gate_id:
        return _error_response(400, "Missing gate ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to view this gate")

        cur.execute("""
            SELECT id, name, estate_id, active, last_controller_heartbeat, date_created, date_updated
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
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
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
            SELECT v.*, pi.expiry
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            LEFT JOIN guests g ON g.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links ga
                JOIN gates g2 ON g2.id = ga.gate_id
                WHERE g2.id = %s
                AND (
                (
                    -- standard case
                    GREATEST(g2.opening_time, ga.opening_time) <= LEAST(g2.closing_time, ga.closing_time)
                    AND CURRENT_TIME BETWEEN GREATEST(g2.opening_time, ga.opening_time)
                    AND LEAST(g2.closing_time, ga.closing_time)
                )
                OR
                (
                    -- crosses midnight
                    GREATEST(g2.opening_time, ga.opening_time) > LEAST(g2.closing_time, ga.closing_time)
                    AND (CURRENT_TIME >= GREATEST(g2.opening_time, ga.opening_time)
                    OR CURRENT_TIME <= LEAST(g2.closing_time, ga.closing_time))
                )
                )
            )
            AND (
                g.id IS NULL
                OR
                (
                (g.other_info->'entry_window'->>'start')::timestamp <= CURRENT_TIMESTAMP
                AND (g.other_info->'entry_window'->>'end')::timestamp >= CURRENT_TIMESTAMP
                )
            );
        """, (gate_id,))
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})

def person_arrives_with_vehicle_callback(conn, body, event):
    """
    Handles vehicle entry and exit for guests and account holders.
    For guests: validates entry window on entry, updates status to CHECKED_IN/CHECKED_OUT.
    For account holders: bypasses entry window check.
    Removes 'otp' and 'entry_window' from other_info upon successful guest entry.
    """
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized. Not a registered gate controller")

    license_plate_number = body.get("license_plate_number", None)
    status = body.get("status", None)

    if not license_plate_number:
        return _error_response(400, "Missing required field: 'license_plate_number'.")

    if not status or status not in ["entry", "exit"]:
        return _error_response(400, "Missing or invalid 'status' field. Must be 'entry' or 'exit'.")

    now = datetime.now()
    action_text = "arrival" if status == "entry" else "departure"
    print(f"License plate: {license_plate_number}\nTime of {action_text}: {now.strftime('%A %d %B %Y %H:%M:%S')}")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Retrieve person info based on license plate
        cur.execute(
            """
            SELECT pi.name, ah.user_id, gah.user_id AS creator_user_id, g.id AS guest_id, g.other_info, g.creator_id,
                   pi.estate_id, ah.id AS account_holder_id
            FROM vehicles v
            JOIN personal_info pi ON pi.id = v.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            LEFT JOIN account_holders gah ON gah.id = g.creator_id
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            WHERE v.license_plate_number = %s
              AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
              AND (g.id IS NOT NULL OR ah.id IS NOT NULL)
            """,
            (license_plate_number, gate_id)
        )
        
        person_data = cur.fetchone()

        if not person_data:
            return _error_response(400, "Vehicle not found or not associated with a guest/account holder.")

        is_guest = person_data["guest_id"] is not None
        
        print(person_data)

        if is_guest:
            other_info = person_data["other_info"] or {}

            if status == "entry":
                # Entry validation - check entry window
                entry_window = other_info.get("entry_window", {})
                start_str = entry_window.get("start")
                end_str = entry_window.get("end")

                if not (start_str and end_str):
                    return _error_response(400, "No valid entry window found for this guest.")

                try:
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                except ValueError:
                    return _error_response(400, "Invalid date format in entry window.")

                if not (start_dt <= now <= end_dt):
                    return _error_response(400, "Guest cannot enter at this time (not yet valid or expired).")

                # Remove OTP and entry window on successful entry
                other_info.pop("otp", None)
                other_info.pop("entry_window", None)
                guest_status = "CHECKED_IN"
                log_action = "GUEST_VEHICLE_ENTRY"
                log_message = f"Guest {person_data['name']} entered with vehicle license plate {license_plate_number}"
                notify_user(str(person_data['creator_user_id']), log_action,log_message)
            else:  # status == "exit"
                # Exit - no validation needed, just update status
                guest_status = "CHECKED_OUT"
                log_action = "GUEST_VEHICLE_EXIT"
                log_message = f"Guest {person_data['name']} exited with vehicle license plate {license_plate_number}"
                notify_user(str(person_data['creator_user_id']), log_action,log_message)
            # Update guest record
            cur.execute(
                """
                UPDATE guests
                SET status = %s, other_info = %s
                WHERE id = %s
                RETURNING id
                """,
                (guest_status, json.dumps(other_info), person_data["guest_id"])
            )
            if not cur.fetchone():
                return _error_response(400, "Guest could not be updated.")
            # cur.execute("""
            #     INSERT INTO AccessLog (license_plate_number, event, timestamp))
            #     VALUES (%s, %s, NOW()
            #     RETURNING id"""),(license_plate_number,status)
            log(conn, log_action, log_message, person_data["creator_user_id"], person_data["creator_id"], person_data["estate_id"])

        else:
            # Account holder — no OTP or time check, just log the appropriate action
            if status == "entry":
                log_action = "ACCOUNT_HOLDER_VEHICLE_ENTRY"
                log_message = f"{person_data['name']} entered with vehicle license plate {license_plate_number}"
                notify_user(str(person_data['user_id']), log_action,log_message)
            else:  # status == "exit"
                log_action = "ACCOUNT_HOLDER_VEHICLE_EXIT"
                log_message = f"{person_data['name']} exited with vehicle license plate {license_plate_number}"
                notify_user(str(person_data['user_id']), log_action,log_message)
            # cur.execute("""
            #     INSERT INTO AccessLog (license_plate_number, event, timestamp))
            #     VALUES (%s, %s, NOW()
            #     RETURNING id"""),(license_plate_number,status)
            log(conn, log_action, log_message, person_data['user_id'], person_data["account_holder_id"], person_data["estate_id"])
        cur.execute("""
                INSERT INTO accesslog (license_plate_number, event, gate_id, timestamp)
                VALUES (%s, %s, %s, NOW())
                RETURNING id""",(license_plate_number,status,gate_id))
        conn.commit()

    action_message = "Gate opened for vehicle entry" if status == "entry" else "Gate opened for vehicle exit"

    return _success_response(
        200,
        {
            "message": action_message,
            "person_name": person_data["name"],
            "type": "guest" if is_guest else "account_holder",
            "status": status,
            "guest_status": guest_status if is_guest else None
        }
    )
    
def get_vehicles_by_gate_with_time_check(conn, event):
    """
    Retrieve vehicles allowed at a gate, considering the gate's time windows.
    This query supports time windows that cross midnight.
    Supports pagination via ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = event.get("pathParameters", {}).get("gate_id")
    if not gate_id:
        return _error_response(400, "Missing gate id in path parameters.")

    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError
    except ValueError:
        return _error_response(400, "Invalid 'page' or 'page_size' parameter.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to view vehicles for this gate.")

        # Count total
        cur.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT v.id
                FROM vehicles v
                JOIN personal_info pi ON v.personal_info_id = pi.id
                LEFT JOIN guests g ON g.personal_info_id = pi.id
                WHERE pi.access_group_id IN (
                    SELECT access_group_id
                    FROM gate_access_group_links ga
                    JOIN gates g2 ON g2.id = ga.gate_id
                    WHERE g2.id = %s
                    AND (
                        (GREATEST(g2.opening_time, ga.opening_time) <= LEAST(g2.closing_time, ga.closing_time)
                          AND CURRENT_TIME BETWEEN GREATEST(g2.opening_time, ga.opening_time)
                          AND LEAST(g2.closing_time, ga.closing_time))
                        OR
                        (GREATEST(g2.opening_time, ga.opening_time) > LEAST(g2.closing_time, ga.closing_time)
                          AND (CURRENT_TIME >= GREATEST(g2.opening_time, ga.opening_time)
                          OR CURRENT_TIME <= LEAST(g2.closing_time, ga.closing_time)))
                    )
                )
                AND (
                    g.id IS NULL
                    OR (
                        (g.other_info->'entry_window'->>'start')::timestamp <= CURRENT_TIMESTAMP
                        AND (g.other_info->'entry_window'->>'end')::timestamp >= CURRENT_TIMESTAMP
                    )
                )
            ) AS valid_vehicles
        """, (gate_id,))
        total = cur.fetchone()["count"]

        # Fetch paginated results
        cur.execute("""
            SELECT v.*, pi.expiry
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            LEFT JOIN guests g ON g.personal_info_id = pi.id
            WHERE pi.access_group_id IN (
                SELECT access_group_id
                FROM gate_access_group_links ga
                JOIN gates g2 ON g2.id = ga.gate_id
                WHERE g2.id = %s
                AND (
                    (GREATEST(g2.opening_time, ga.opening_time) <= LEAST(g2.closing_time, ga.closing_time)
                      AND CURRENT_TIME BETWEEN GREATEST(g2.opening_time, ga.opening_time)
                      AND LEAST(g2.closing_time, ga.closing_time))
                    OR
                    (GREATEST(g2.opening_time, ga.opening_time) > LEAST(g2.closing_time, ga.closing_time)
                      AND (CURRENT_TIME >= GREATEST(g2.opening_time, ga.opening_time)
                      OR CURRENT_TIME <= LEAST(g2.closing_time, ga.closing_time)))
                )
            )
            AND (
                g.id IS NULL
                OR (
                    (g.other_info->'entry_window'->>'start')::timestamp <= CURRENT_TIMESTAMP
                    AND (g.other_info->'entry_window'->>'end')::timestamp >= CURRENT_TIMESTAMP
                )
            )
            ORDER BY v.date_created DESC
            LIMIT %s OFFSET %s
        """, (gate_id, page_size, offset))
        vehicles = cur.fetchall()

    return _success_response(200, {
        "vehicles": process_db_results(vehicles),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

def activate_gate(conn, body, event):
    """
    Activates a gate. Only accessible by global admins or users with MANAGE_GATES/MANAGE_ALL privileges.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("id")
    if not gate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to manage gates")

        cur.execute("""
            UPDATE gates
            SET active = true, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING estate_id, name
        """, (gate_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Gate not found.")

        log(conn, "GATE_ACTIVATION",
            f"Gate '{gate_id}' [{result['name']}] activated",
            user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Gate activated successfully.", "gate_id": gate_id})

def deactivate_gate(conn, body, event):
    """
    Deactivates a gate. Only accessible by global admins or users with MANAGE_GATES/MANAGE_ALL privileges.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("id")
    if not gate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_gate(cur, user_id, gate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in the estate for this gate")

        if not privileges.can_manage_gates():
            return _error_response(403, "You do not have privileges to manage gates")

        cur.execute("""
            UPDATE gates
            SET active = false, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING estate_id, name
        """, (gate_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Gate not found.")

        log(conn, "GATE_DEACTIVATION",
            f"Gate '{gate_id}' [{result['name']}] deactivated",
            user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Gate deactivated successfully.", "gate_id": gate_id})

