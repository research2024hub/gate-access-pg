import json
from psycopg2.extras import RealDictCursor
import random
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges
from middleware import verify_token
from datetime import datetime
import jwt
import os

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")

def use_invite_token(conn, body, event):
    """
    Uses an invite link token to register a guest for an event.
    Token is passed as a query parameter (?token=...).
    """
    token = event.get("queryStringParameters", {}).get("token")
    if not token:
        return _error_response(400, "Missing invite token.")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return _error_response(403, "Invite token has expired.")
    except jwt.InvalidTokenError:
        return _error_response(403, "Invalid invite token.")

    # Extract data from token
    event_id = payload.get("event_id")
    account_holder_id = payload.get("account_holder_id")
    event_name = payload.get("event_name")
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")

    # Guest details from request body
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")

    if not all([name, id_type, id_num, contact]):
        return _error_response(400, "Missing guest details: 'name', 'id_type', 'id_num', or 'contact'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get estate_id from creator
        cur.execute("""
            SELECT pi.estate_id
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            WHERE ah.id = %s
        """, (account_holder_id,))
        row = cur.fetchone()
        if not row:
            return _error_response(404, "Creator account not found.")
        estate_id = row["estate_id"]

        # Generate unique OTP
        while True:
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM guests g
                    JOIN personal_info pi ON pi.id = g.personal_info_id
                    WHERE g.other_info->>'otp' = %s AND pi.estate_id = %s
                ) AS otp_exists
            """, (otp, estate_id))
            if not cur.fetchone()["otp_exists"]:
                break

        expiry = datetime.fromisoformat(end_time)

        other_info = {
            "otp": otp,
            "purpose": "event",
            "entry_window": {
                "start": start_time,
                "end": end_time
            }
        }

        # 1. Insert into personal_info
        cur.execute("""
            INSERT INTO personal_info (
                estate_id, name, id_type, id_num, contact, expiry,
                account_type_id, access_group_id
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                (SELECT id FROM account_types WHERE name = 'GUEST'),
                (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR')
            )
            RETURNING id
        """, (estate_id, name, id_type, id_num, contact, expiry, estate_id))
        personal_info_id = cur.fetchone()["id"]

        # 2. Insert into guests
        cur.execute("""
            INSERT INTO guests (personal_info_id, creator_id, other_info)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (personal_info_id, account_holder_id, json.dumps(other_info)))
        guest_id = cur.fetchone()["id"]

        # 3. Insert into event_registers
        cur.execute("""
            INSERT INTO event_registers (event_id, guest_id)
            VALUES (%s, %s)
            RETURNING id
        """, (event_id, guest_id))
        register_id = cur.fetchone()["id"]

        log(conn, "EVENT_REGISTER_ENTRY_CREATED",
            f"Guest {name} registered for event '{event_id}' [{event_name}] via invite",
            account_holder_id, account_holder_id, estate_id)

        conn.commit()

    return _success_response(201, {
        "message": "Guest registered successfully via invite link.",
        "event_register_id": register_id,
        "guest_id": guest_id,
        "personal_info_id": personal_info_id,
        "otp": otp
    })

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
            SELECT start_time, end_time, name
            FROM events
            WHERE id = %s
        """, (event_id,))
        event_data = cur.fetchone()

        if not event_data:
            return _error_response(404, "Event not found.")

        # 2) Privilege check using helper
        # Get event creator to establish privilege context
        cur.execute("""
            SELECT e.creator_id
            FROM events e
            WHERE e.id = %s
        """, (event_id,))

        event_creator_result = cur.fetchone()
        if not event_creator_result:
            return _error_response(404, "Event not found.")

        creator_id = event_creator_result["creator_id"]

        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, creator_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_events (estate-wide) or owns this event (create_events + is_same_person)
        if not privileges.can_manage_or_own_events():
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

        log(conn, "EVENT_REGISTER_ENTRY_CREATED", f"Guest {name} registered for event '{event_id}' [{event_data['name']}]", user_id, account_holder_id, estate_id)
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
    Supports query parameters: ?page=1&page_size=20
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
        cur.execute("SELECT creator_id FROM events WHERE id = %s", (event_id,))
        event_data = cur.fetchone()
        if not event_data:
            return _error_response(404, "Event not found.")

        creator_id = event_data["creator_id"]

        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, creator_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_events (estate-wide) or owns this event (create_events + is_same_person)
        if not privileges.can_manage_or_own_events():
            return _error_response(403, "You do not have privileges to retrieve this event's guests")

        # Get total number of guests
        cur.execute("""
            SELECT COUNT(*) 
            FROM event_registers er
            JOIN guests g ON er.guest_id = g.id
            JOIN personal_info pi ON g.personal_info_id = pi.id
            WHERE er.event_id = %s
        """, (event_id,))
        total = cur.fetchone()["count"]

        # Fetch paginated guest data
        cur.execute("""
            SELECT g.id AS guest_id, pi.name AS guest_name, pi.contact, pi.estate_id
            FROM event_registers er
            JOIN guests g ON er.guest_id = g.id
            JOIN personal_info pi ON g.personal_info_id = pi.id
            WHERE er.event_id = %s
            ORDER BY pi.name ASC
            LIMIT %s OFFSET %s
        """, (event_id, page_size, offset))
        
        guests = cur.fetchall()

    return _success_response(200, {
        "event_id": event_id,
        "guests": process_db_results(guests),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

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

        creator_id = event_data["creator_id"]

        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, creator_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_events (estate-wide) or owns this event (create_events + is_same_person)
        if not privileges.can_manage_or_own_events():
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
        
        log(conn, "EVENT_REGISTER_ENTRY_REMOVED", f"Guest '{guest_id}' removed from event '{event_id}' [{result['name']}]", user_id, result["creator_id"], result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Guest removed from event successfully, all related data deleted."})
