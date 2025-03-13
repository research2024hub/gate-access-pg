import json
from psycopg2.extras import RealDictCursor
import random
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def register_guest_for_event(conn, body, event):
    """
    Registers a guest for an event by creating a new guest dynamically.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")
    
    account_holder_id = body.get("account_holder_id")
    event_id = body.get("event_id")
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    other_info = body.get("other_info", {})  # Default to empty dict

    # Basic validation of required fields
    if not all([account_holder_id, event_id, name, id_type, id_num, contact]):
        return _error_response(400, "Missing required fields.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1) Confirm the event exists and retrieve start/end times
        cur.execute("""
            SELECT start_time, end_time
            FROM events
            WHERE id = %s
        """, (event_id,))
        event_data = cur.fetchone()

        if not event_data:
            return _error_response(404, "Event not found.")

        # 2) Privilege check
        cur.execute("""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s
                      AND pi.estate_id = (
                          SELECT pi.estate_id
                          FROM events e
                          JOIN account_holders ah ON e.creator_id = ah.id
                          JOIN personal_info pi ON ah.personal_info_id = pi.id
                          WHERE e.id = %s
                      )
                      AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                ) AS has_privileges,
                EXISTS (
                    SELECT 1
                    FROM events e
                    JOIN account_holders ah ON e.creator_id = ah.id
                    WHERE ah.user_id = %s
                      AND e.id = %s
                      AND ah.id = %s
                ) AS is_owner
        """, (user_id, event_id, user_id, event_id, account_holder_id))
        
        priv_check = cur.fetchone()

        if not (priv_check["has_privileges"] or priv_check["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to register guests for this event")

        # 3) Generate a unique 6-digit OTP
        while True:
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM guests g
                    JOIN personal_info pi ON pi.id = g.personal_info_id
                    WHERE g.other_info->>'otp' = %s
                      AND pi.estate_id = (
                          SELECT pi.estate_id
                          FROM events e 
                          JOIN account_holders ah ON e.creator_id = ah.id
                          JOIN personal_info pi ON pi.id = ah.personal_info_id
                          WHERE e.id = %s
                      )
                ) AS otp_exists
            """, (otp, event_id))
            if not cur.fetchone()["otp_exists"]:
                break
        
        # 4) Populate other_info with OTP and event window
        other_info["otp"] = otp
        other_info["purpose"] = "event"
        other_info["entry_window"] = {
            "start": event_data["start_time"].isoformat(),
            "end":   event_data["end_time"].isoformat()
        }

        cur.execute("""
            SELECT pi.estate_id
            FROM personal_info pi
            JOIN account_holders ah ON ah.personal_info_id = pi.id
            WHERE ah.id = %s
        """, (account_holder_id,))
        row = cur.fetchone()
        if not row or not row["estate_id"]:
            return _error_response(400, "Could not determine estate_id from account_holder_id.")

        estate_id = row["estate_id"]
        expiry = event_data["end_time"]

        # 5) Create personal_info entry for the guest
        cur.execute("""
            INSERT INTO personal_info (
                estate_id,
                name,
                id_type,
                id_num,
                contact,
                expiry,
                account_type_id,
                access_group_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name = 'GUEST'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
            RETURNING id
        """, (estate_id, name, id_type, id_num, contact, expiry, estate_id))
        personal_info_id = cur.fetchone()["id"]

        # 6) Create guest entry with the other_info (JSON)
        cur.execute("""
            INSERT INTO guests (personal_info_id, creator_id, other_info)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (personal_info_id, account_holder_id, json.dumps(other_info)))
        guest_id = cur.fetchone()["id"]

        # 7) Register guest for the event in event_registers
        cur.execute("""
            INSERT INTO event_registers (event_id, guest_id)
            VALUES (%s, %s)
            RETURNING id
        """, (event_id, guest_id))
        register_id = cur.fetchone()["id"]

        log(conn, "EVENT_REGISTER_ENTRY_CREATED", f"Guest {name} registered for event '{event_id}'", user_id, account_holder_id, estate_id)
        # 8) Commit the transaction
        conn.commit()

    return _success_response(201, {
        "message": "Guest registered successfully for the event.",
        "event_register_id": register_id,
        "guest_id": guest_id,
        "personal_info_id": personal_info_id
    })


def list_event_guests(conn, event):
    """
    Lists all guests registered for a specific event.
    Only the event creator or an admin can access this data.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    path_params = event.get("pathParameters", {})
    event_id = path_params.get("event_id")

    if not event_id:
        return _error_response(400, "Missing 'event_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT creator_id FROM events WHERE id = %s", (event_id,))
        event_data = cur.fetchone()
        if not event_data:
            return _error_response(404, "Event not found.")
    
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM events e
                            JOIN account_holders ah ON e.creator_id = ah.id
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE e.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (
                        SELECT 1 FROM events e 
                        JOIN account_holders ah ON e.creator_id = ah.id
                        WHERE ah.user_id = %s AND e.id = %s
                    ) AS is_owner
                    """, (user_id, event_id, user_id, event_id))
        
        result = cur.fetchone()

        if not (result["has_privileges"] or result["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to retrieve this event's guests")
                
        # Fetch guests registered for the event
        cur.execute("""
            SELECT g.id AS guest_id, pi.name AS guest_name, pi.contact, pi.estate_id
            FROM event_registers er
            JOIN guests g ON er.guest_id = g.id
            JOIN personal_info pi ON g.personal_info_id = pi.id
            WHERE er.event_id = %s
        """, (event_id,))
        
        guests = cur.fetchall()

    return _success_response(200, {"event_id": event_id, "guests": process_db_results(guests)})


def remove_guest_from_event(conn, body, event):
    """
    Removes a guest from an event. If the guest is removed, their personal_info is also deleted, 
    which cascades and removes all related records.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    event_id = body.get("event_id")
    guest_id = body.get("guest_id")

    if not (event_id and guest_id):
        return _error_response(400, "Missing 'event_id' or 'guest_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT creator_id FROM events WHERE id = %s", (event_id,))
        event_data = cur.fetchone()
        if not event_data:
            return _error_response(404, "Event not found.")
    
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM events e
                            JOIN account_holders ah ON e.creator_id = ah.id
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE e.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (
                        SELECT 1 FROM events e 
                        JOIN account_holders ah ON e.creator_id = ah.id
                        WHERE ah.user_id = %s AND e.id = %s
                    ) AS is_owner
                    """, (user_id, event_id, user_id, event_id))
        
        result = cur.fetchone()

        if not (result["has_privileges"] or result["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to remove this event's guests")

        # Delete personal_info (which cascades deletion for guest & event_registers)
        cur.execute("DELETE FROM personal_info WHERE id = (SELECT personal_info_id FROM guests WHERE id = %s) RETURNING id", (guest_id,))
        if not cur.fetchone():
            return _error_response(500, "Failed to delete guest.")
        
        cur.execute("""
                    SELECT pi.estate_id, e.creator_id, e.name FROM events e 
                    JOIN account_holders ah ON ah.id = e.creator_id
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE e.id = %s
                    """, (event_id,))
        
        result = cur.fetchone()
        
        log(conn, "EVENT_REGISTER_ENTRY_REMOVED", f"Guest '{guest_id}' removed from event '{event_id}' [{result["name"]}]", user_id, result["creator_id"], result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Guest removed from event successfully, all related data deleted."})