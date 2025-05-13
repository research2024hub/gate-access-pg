import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token
from datetime import datetime, timedelta
import jwt
import os

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")
INVITE_EXPIRY_HOURS = 24
INVITE_BASE_URL = "https://gate-access-web.vercel.app/invite"

def generate_event_invite_link(conn, body, event):
    """
    Generates a signed invite link for an event. Only the creator, authorized estate manager, or global admin can generate it.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    event_id = body.get("event_id")

    if not event_id:
        return _error_response(400, "Missing 'event_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Get event details
        cur.execute("""
            SELECT 
                e.id AS event_id,
                e.name AS event_name,
                e.start_time,
                e.end_time,
                ah.id AS creator_account_holder_id,
                pi.name AS creator_name,
                es.name AS estate_name,
                pi.estate_id
            FROM events e
            JOIN account_holders ah ON e.creator_id = ah.id
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            WHERE e.id = %s
        """, (event_id,))
        event_info = cur.fetchone()

        if not event_info:
            return _error_response(404, "Event not found.")

        is_creator = event_info["creator_account_holder_id"] == body.get("account_holder_id")

        # 2. Check permission if not creator or admin
        has_privileges = False
        if not is_creator and not is_admin:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = %s
                    AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                ) AS has_privileges
            """, (user_id, event_info["estate_id"]))
            has_privileges = cur.fetchone()["has_privileges"]

        if not (is_creator or has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to generate an invite link for this event.")

        # 3. Prepare token payload
        token_payload = {
            "event_id": event_info["event_id"],
            "account_holder_id": event_info["creator_account_holder_id"],
            "event_name": event_info["event_name"],
            "creator_name": event_info["creator_name"],
            "estate_name": event_info["estate_name"],
            "start_time": event_info["start_time"].isoformat(),
            "end_time": event_info["end_time"].isoformat(),
            "exp": datetime.utcnow() + timedelta(hours=INVITE_EXPIRY_HOURS)
        }

        token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")
        invite_url = f"{INVITE_BASE_URL}?token={token}"

        log(conn, "INVITE_GENERATED", f"Invite link created for event '{event_info['event_name']}'", user_id, event_info["creator_account_holder_id"], event_info["estate_id"])

        conn.commit()

    return _success_response(200, {
        "message": "Event invite link generated successfully.",
        "invite_url": invite_url,
        "expires_in_hours": INVITE_EXPIRY_HOURS
    })

def create_event(conn, body, event):
    """
    Creates a new event. Only account holders can create events.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    creator_id = body.get("creator_id")
    name = body.get("name")
    max_num_of_attendees = body.get("max_num_of_attendees")
    start_time = body.get("start_time")
    end_time = body.get("end_time")

    if not all([creator_id, name, max_num_of_attendees, start_time, end_time]):
        return _error_response(400, "Missing required fields.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (SELECT 1 FROM account_holders ah WHERE ah.user_id = %s AND ah.is_active = TRUE AND ah.id = %s) as same_person
                    """, (user_id, creator_id, user_id, creator_id))
        result = cur.fetchone()
        if not (result[0] or result[1] or is_admin):
            return _error_response(403, "You do not have privileges to create an event for this account")

        # Insert new event
        cur.execute("""
            INSERT INTO events (creator_id, name, max_num_of_attendees, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (creator_id, name, max_num_of_attendees, start_time, end_time))
        
        event_id = cur.fetchone()[0]

        # Generate invite link
        invite_response = generate_event_invite_link(
            conn, {"event_id": event_id, "account_holder_id": creator_id}, event
        )

        if invite_response["statusCode"] != 200:
            return _error_response(500, "Event created but failed to generate invite link.")
        
        invite_url = json.loads(invite_response["body"])["invite_url"]

        cur.execute("""
                    SELECT pi.estate_id FROM account_holders ah 
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.id = %s
                    """, (creator_id,))
        
        result = cur.fetchone()

        log(conn, "EVENT_CREATION", f"Event '{event_id}' [{name}] created", user_id, creator_id, result[0])
        
        conn.commit()

    return _success_response(201, {
        "message": "Event created successfully.",
        "event_id": event_id,
        "invite_url": invite_url
    })


def update_event(conn, body, event):
    """
    Updates an existing event. Only the event creator or an admin can update.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    event_id = body.get("event_id")
    name = body.get("name")
    max_num_of_attendees = body.get("max_num_of_attendees")
    start_time = body.get("start_time")
    end_time = body.get("end_time")

    if not (event_id):
        return _error_response(400, "Missing 'event_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN events e ON e.creator_id = ah.id
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE e.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (
                        SELECT 1 FROM events e
                        JOIN account_holders ah ON e.creator_id = ah.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND e.id = %s) as is_owner
                    """, (user_id, event_id, user_id, event_id))
        
        result = cur.fetchone()
        if not (result["has_privileges"] or result["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to manage this event")

        # Update event details
        cur.execute("""
            UPDATE events
            SET name = COALESCE(%s, name),
                max_num_of_attendees = COALESCE(%s, max_num_of_attendees),
                start_time = COALESCE(%s, start_time),
                end_time = COALESCE(%s, end_time)
            WHERE id = %s
            RETURNING id
        """, (name, max_num_of_attendees, start_time, end_time, event_id))

        if not cur.fetchone():
            return _error_response(500, "Failed to update event.")
        
        cur.execute("""
                    SELECT pi.estate_id FROM events e 
                    JOIN account_holders ah ON ah.id = e.creator_id
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE e.id = %s
                    """, (event_id,))
        
        result = cur.fetchone()

        log(conn, "EVENT_UPDATE", f"Event '{event_id}' [{name}] updated", user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Event updated successfully."})

def delete_event(conn, body, event):
    """
    Deletes an event. Only the event creator or an admin can delete it.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    event_id = body.get("event_id")

    if not (event_id):
        return _error_response(400, "Missing 'event_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Verify privileges
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN events e ON e.creator_id = ah.id
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE e.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (
                        SELECT 1 FROM events e
                        JOIN account_holders ah ON e.creator_id = ah.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND e.id = %s) as is_owner
                    """, (user_id, event_id, user_id, event_id))

        result = cur.fetchone()
        if not (result["has_privileges"] or result["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to delete this event")

        # 2. Fetch event info BEFORE deleting
        cur.execute("""
            SELECT pi.estate_id, e.name 
            FROM events e 
            JOIN account_holders ah ON ah.id = e.creator_id
            JOIN personal_info pi ON pi.id = ah.personal_info_id
            WHERE e.id = %s
        """, (event_id,))

        event_info = cur.fetchone()
        if not event_info:
            return _error_response(404, "Event not found.")

        # 3. Now delete the event
        cur.execute("DELETE FROM events WHERE id = %s RETURNING id", (event_id,))
        if not cur.fetchone():
            return _error_response(500, "Failed to delete event.")

        # 4. Log deletion
        log(conn, "EVENT_DELETION", f"Event '{event_id}' [{event_info['name']}] deleted", user_id, None, event_info["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Event deleted successfully."})


def get_event_details(conn, event):
    """
    Retrieves details of a specific event.
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
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN events e ON e.creator_id = ah.id
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE e.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (
                        SELECT 1 FROM events e
                        JOIN account_holders ah ON e.creator_id = ah.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND e.id = %s) as is_owner
                    """, (user_id, event_id, user_id, event_id))
        
        result = cur.fetchone()
        if not (result["has_privileges"] or result["is_owner"] or is_admin):
            return _error_response(403, "You do not have privileges to retrieve details of this event")     
        
        cur.execute("""
            SELECT e.id, e.name, e.max_num_of_attendees, e.start_time, e.end_time, ah.id AS creator_id, pi.name AS creator_name
            FROM events e
            JOIN account_holders ah ON e.creator_id = ah.id
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            WHERE e.id = %s
        """, (event_id,))
        
        event_details = cur.fetchone()
        if not event_details:
            return _error_response(404, "Event not found.")

    return _success_response(200, {"event": process_db_results([event_details])})

def list_events_by_creator(conn, event):
    """
    Lists all events created by a specific account holder.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    path_params = event.get("pathParameters", {})
    creator_id = path_params.get("account_holder_id")

    if not creator_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges,
                    EXISTS (SELECT 1 FROM account_holders ah WHERE ah.user_id = %s AND ah.is_active = TRUE AND ah.id = %s) as same_person
                    """, (user_id, creator_id, user_id, creator_id))
        result = cur.fetchone()
        if not (result["has_privileges"] or result["same_person"] or is_admin):
            return _error_response(403, "You do not have privileges to retrieve events for this account")
        
        cur.execute("""
            SELECT id, name, max_num_of_attendees, start_time, end_time
            FROM events
            WHERE creator_id = %s
        """, (creator_id,))
        
        events = cur.fetchall()

    return _success_response(200, {"events": process_db_results(events)})

def list_events_by_estate(conn, event):
    """
    Lists all events in a specific estate by filtering via creator_id.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")
    
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")

    if not estate_id:
        return _error_response(400, "Missing 'estate_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND ah.is_active = TRUE AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_EVENTS')
                    ) AS has_privileges
                    """, (user_id, estate_id))
        
        has_privileges = cur.fetchone()["has_privileges"]

        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to get events from this estate")

        cur.execute("""
            SELECT e.id, e.name, e.max_num_of_attendees, e.start_time, e.end_time, ah.id AS creator_id, pi.name AS creator_name
            FROM events e
            JOIN account_holders ah ON e.creator_id = ah.id
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            WHERE pi.estate_id = %s
        """, (estate_id,))
        
        events = cur.fetchall()

    return _success_response(200, {"events": process_db_results(events)})