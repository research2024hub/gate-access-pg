import json
import random
from psycopg2.extras import RealDictCursor
from datetime import datetime
from utils import _error_response, _success_response, process_db_results, send_message, log
from middleware import verify_token

def create_guest_regular(conn, body, event):
    """
    Registers a new guest under an account holder and creates a corresponding personal_info entry.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    account_holder_id = body.get("account_holder_id")
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    expiry = body.get("expiry")
    start = body.get("start", None)
    other_info = body.get("other_info", {})

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    start =  start if start else now
    other_info["entry_window"] = {
        "start": start,
        "end": expiry
    }
    
    if not all([account_holder_id, name, id_type, id_num, contact, expiry]):
        return _error_response(400, "Missing required fields.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (
                            SELECT pi.estate_id
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            cur.execute("""
                SELECT EXISTS(SELECT 1 FROM account_holders ah
                        WHERE ah.id = %s AND ah.user_id = %s) as same_person
                """, (account_holder_id, user_id))
            row = cur.fetchone()
            if not row["same_person"]:
                return _error_response(403, "You do not have privileges to create a guest for this account.")
        
        # Retrieve the estate_id linked to the account holder
        cur.execute("""
        SELECT pi.estate_id, es.name AS estate_name
        FROM personal_info pi
        JOIN account_holders ah ON ah.personal_info_id = pi.id 
        JOIN estates es ON es.id = pi.estate_id 
        WHERE ah.id = %s
        """, (account_holder_id,))

        result = cur.fetchone()

        if not result:
            return _error_response(400, "No estate found for this account holder.")

        estate_id = result["estate_id"]
        estate_name = result["estate_name"]

        # Create personal_info entry
        cur.execute("""
            INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, expiry, account_type_id, access_group_id)
            VALUES (%s, %s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name = 'GUEST'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
            RETURNING id
        """, (estate_id, name, id_type, id_num, contact, expiry, estate_id))
        personal_info_id = cur.fetchone()["id"]

        # Make sure there aren't duplicates
        while True:
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])

            cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM guests g
                            JOIN personal_info pi ON pi.id = g.personal_info_id
                            WHERE g.other_info->>'otp' = %s AND pi.estate_id = %s
                        ) AS otp_match
                        """, (otp, estate_id))

            if not cur.fetchone()["otp_match"]:
                break

        other_info["otp"] = otp
        other_info["purpose"] = "visit"

        # Create guest entry
        cur.execute("""
            INSERT INTO guests (personal_info_id, creator_id, other_info)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (personal_info_id, account_holder_id, json.dumps(other_info)))
        guest_id = cur.fetchone()["id"]

        log(conn, "GUEST_CREATION", f"Guest '{guest_id}' [{name}] created", user_id, account_holder_id, estate_id)

        conn.commit()

        expiry_date_readable = datetime.fromisoformat(expiry).strftime("%A, %d %B %Y %H:%M:%S")
        start_date_readable = datetime.fromisoformat(start).strftime("%A, %d %B %Y %H:%M:%S")

        phone_number = contact.lstrip('+')

        send_message(phone_number, f"Hi {name},\nYour One Time Password (OTP) for your visit at {estate_name} is {otp}, valid from {start_date_readable} to {expiry_date_readable}")

        print(f"Window Opens: {start_date_readable}, Window Closes:{expiry_date_readable}")

    return _success_response(201, {"message": "Guest registered successfully.", "guest_id": guest_id, "personal_info_id": personal_info_id})

def create_associate(conn, body, event):
    """
    Registers a new guest under an account holder and creates a corresponding personal_info entry.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    account_holder_id = body.get("account_holder_id")
    account_type_id = body.get("account_type_id")
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    expiry = body.get("expiry")
    start = body.get("start", None)
    other_info = body.get("other_info", {})

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    start =  start if start else now
    other_info["entry_window"] = {
        "start": start,
        "end": expiry
    }
    
    if not all([account_holder_id, name, id_type, id_num, contact, expiry, account_type_id]):
        return _error_response(400, "Missing required fields.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (
                            SELECT pi.estate_id
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            cur.execute("""
                SELECT EXISTS(SELECT 1 FROM account_holders ah
                        WHERE ah.id = %s AND ah.user_id = %s) as same_person
                """, (account_holder_id, user_id))
            row = cur.fetchone()
            if not row["same_person"]:
                return _error_response(403, "You do not have privileges to create a guest for this account.")
        
        # Retrieve the estate_id linked to the account holder
        cur.execute("""
        SELECT pi.estate_id, es.name AS estate_name
        FROM personal_info pi
        JOIN account_holders ah ON ah.personal_info_id = pi.id 
        JOIN estates es ON es.id = pi.estate_id 
        WHERE ah.id = %s
        """, (account_holder_id,))

        result = cur.fetchone()

        if not result:
            return _error_response(400, "No estate found for this account holder.")

        estate_id = result["estate_id"]
        estate_name = result["estate_name"]

        # Create personal_info entry
        cur.execute("""
            INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, expiry, account_type_id, access_group_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
            RETURNING id
        """, (estate_id, name, id_type, id_num, contact, expiry, account_type_id, estate_id))
        personal_info_id = cur.fetchone()["id"]

        # Make sure there aren't duplicates
        while True:
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])

            cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM guests g
                            JOIN personal_info pi ON pi.id = g.personal_info_id
                            WHERE g.other_info->>'otp' = %s AND pi.estate_id = %s
                        ) AS otp_match
                        """, (otp, estate_id))

            if not cur.fetchone()["otp_match"]:
                break

        other_info["otp"] = otp
        other_info["purpose"] = "visit"

        # Create guest entry
        cur.execute("""
            INSERT INTO guests (personal_info_id, creator_id, other_info)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (personal_info_id, account_holder_id, json.dumps(other_info)))
        guest_id = cur.fetchone()["id"]

        log(conn, "GUEST_CREATION", f"Guest '{guest_id}' [{name}] created", user_id, account_holder_id, estate_id)

        conn.commit()

        expiry_date_readable = datetime.fromisoformat(expiry).strftime("%A, %d %B %Y %H:%M:%S")
        start_date_readable = datetime.fromisoformat(start).strftime("%A, %d %B %Y %H:%M:%S")

        phone_number = contact.lstrip('+')

        send_message(phone_number, f"Hi {name},\nYour One Time Password (OTP) for your visit at {estate_name} is {otp}, valid from {start_date_readable} to {expiry_date_readable}")

        print(f"Window Opens: {start_date_readable}, Window Closes:{expiry_date_readable}")

    return _success_response(201, {"message": "Guest registered successfully.", "guest_id": guest_id, "personal_info_id": personal_info_id})

def send_otp(conn, body, event):
    """
    Sends (or updates) an OTP for an existing guest.
    - Expects:
        - account_holder_id
        - guest_id
        - expiry
        - optional 'start'
    """

    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    # Fetch required fields from the request body
    account_holder_id = body.get("account_holder_id")
    guest_id = body.get("guest_id")
    expiry = body.get("expiry")
    start = body.get("start", None)

    # Validate required fields
    if not all([account_holder_id, guest_id, expiry]):
        return _error_response(
            400,
            "Missing required fields. 'account_holder_id', 'guest_id', and 'expiry' are required."
        )

    # Default 'start' to now if not provided
    start = start if start else datetime.now().isoformat()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1) Privilege check (similar to your original logic)
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s
                  AND pi.estate_id = (
                      SELECT pi.estate_id
                      FROM account_holders ah
                      JOIN personal_info pi ON ah.personal_info_id = pi.id
                      WHERE ah.id = %s
                  )
                  AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
            ) AS has_privileges
        """, (user_id, account_holder_id))

        row = cur.fetchone()
        has_privileges = row["has_privileges"] if row else False

        if not (has_privileges or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""SELECT g.personal_info_id FROM guests g 
                        JOIN account_holders ah ON ah.id = g.creator_id 
                        WHERE g.id = %s AND ah.user_id = %s""", (guest_id, user_id))
            row = cur.fetchone()
            if not row:
                return _error_response(403, "You do not have privileges to send an OTP to this guest.")

        # 2) Fetch existing guest info, including the current other_info
        cur.execute("""
            SELECT g.id AS guest_id,
                   pi.id AS personal_info_id,
                   pi.contact,
                   pi.name,
                   pi.estate_id,
                   es.name AS estate_name,
                   g.other_info
            FROM guests g
            JOIN personal_info pi ON g.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            WHERE g.id = %s
        """, (guest_id,))
        guest_data = cur.fetchone()

        if not guest_data:
            return _error_response(404, "Guest not found.")

        contact = guest_data["contact"]
        estate_id = guest_data["estate_id"]
        estate_name = guest_data["estate_name"]
        existing_info = guest_data["other_info"] or {}  # keep what's already in other_info

        # 3) Generate a unique 6-digit OTP (ensure no duplicates for that estate)
        while True:
            otp = ''.join(str(random.randint(0, 9)) for _ in range(6))
            cur.execute("""
                SELECT EXISTS(
                    SELECT 1
                    FROM guests g
                    JOIN personal_info pi ON pi.id = g.personal_info_id
                    WHERE g.other_info->>'otp' = %s
                      AND pi.estate_id = %s
                ) AS otp_exists
            """, (otp, estate_id))
            if not cur.fetchone()["otp_exists"]:
                break

        # 4) Update only the relevant parts of other_info
        existing_info["otp"] = otp
        existing_info["entry_window"] = {
            "start": start,
            "end":   expiry
        }

        # 5) Update the guests table with the new other_info
        cur.execute("""
            UPDATE guests
            SET other_info = %s
            WHERE id = %s
            RETURNING id
        """, (json.dumps(existing_info), guest_id))
        updated_row = cur.fetchone()
        if not updated_row:
            return _error_response(400, "Failed to update OTP for the guest.")
        
        log(conn, "GUEST_OTP_SENT", f"OTP sent to guest '{guest_id}' [{guest_data['name']}]", user_id, account_holder_id, estate_id)

        conn.commit()

        # 6) Send SMS if we have a contact phone number
        # Strip leading '+', if present
        phone_number = contact.lstrip('+')
        # Nicely format the start & expiry times
        start_date_readable = datetime.fromisoformat(start).strftime(
            "%A, %d %B %Y %H:%M:%S"
        )
        expiry_date_readable = datetime.fromisoformat(expiry).strftime(
            "%A, %d %B %Y %H:%M:%S"
        )

        send_message(
            phone_number,
            (
                f"Hi {guest_data['name']},\nYour One Time Password (OTP) for your visit at {estate_name} "
                f"is {otp}, valid from {start_date_readable} to {expiry_date_readable}"
            )
        )

    return _success_response(
        200,
        {
            "message": "OTP generated and sent successfully.",
            "guest_name": guest_data["name"]
        }
    )

def verify_guest_otp(conn, body, event):
    """
    Verifies a guest's OTP and checks that the current time is within the allowed entry window.
    Removes 'otp' and 'entry_window' from other_info upon successful verification.
    """
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "TABLET"):
        return _error_response(401, "Unauthorized. Not a registered tablet")

    otp = body.get("otp")
    if not otp:
        return _error_response(400, "Missing required fields: 'otp'.")

    now = datetime.now()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Retrieve the guest info based on the provided OTP
        cur.execute(
            """
            SELECT pi.name, g.id, g.other_info, pi.estate_id, g.creator_id, ah.user_id AS inviter_user_id,
            FROM guests g
            JOIN personal_info pi ON pi.id = g.personal_info_id
            JOIN account_holders ah ON ah.id = g.creator_id
            WHERE g.other_info->>'otp' = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
            """,
            (otp, gate_id)
        )
        guest_data = cur.fetchone()

        # If no guest record matches the OTP, return error
        if not guest_data:
            return _error_response(400, "Invalid OTP")

        other_info = guest_data["other_info"] or {}
        entry_window = other_info.get("entry_window", {})
        start_str = entry_window.get("start")
        end_str = entry_window.get("end")

        # If we cannot find a valid entry window, return an error
        if not (start_str and end_str):
            return _error_response(400, "No valid entry window found for this OTP.")

        # Convert the start and end strings to datetime objects
        try:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str)
        except ValueError:
            return _error_response(400, "Invalid date format in entry window.")

        # Check if the current time is within [start_dt, end_dt]
        if not (start_dt <= now <= end_dt):
            return _error_response(400, "OTP is not valid at this time (not yet valid or expired).")

        # Remove the 'otp' and 'entry_window' entries
        other_info.pop('otp', None)
        other_info.pop('entry_window', None)

        # Update the guest status and other_info
        cur.execute(
            """
            UPDATE guests
            SET other_info = %s
            WHERE id = %s
            RETURNING id
            """,
            (json.dumps(other_info), guest_data["id"])
        )

        updated_row = cur.fetchone()
        if not updated_row:
            return _error_response(400, "Guest does not exist or could not be updated.")
        
        log(conn, "GUEST_OTP_VERIFIED", f"OTP verified by guest '{guest_data['id']}' [{guest_data['name']}]", None, guest_data["creator_id"], guest_data["estate_id"])

        # Commit the changes
        conn.commit()

    return _success_response(
        200,
        {
            "message": "OTP matched successfully",
            "guest_name": guest_data["name"],
            "guest_id": guest_data["id"],
            "inviter_user_id": guest_data["inviter_user_id"]
        }
    )

def guest_arrives_with_vehicle_callback(conn, body, event):
    """
    Verifies a guest's OTP and checks that the current time is within the allowed entry window.
    Removes 'otp' and 'entry_window' from other_info upon successful verification.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized. Not a registered gate controller")

    license_plate_number = body.get("license_plate_number", None)
    if not license_plate_number:
        return _error_response(400, "Missing required fields: 'license_plate_number'.")

    now = datetime.now()
    print(f"License plate: {license_plate_number}\nTime of arrival: {now.strftime('%A %d %B %Y %H:%M:%S')}")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Retrieve the guest info based on the provided OTP
        cur.execute(
            """
            SELECT pi.name, g.id, g.other_info, g.creator_id, pi.estate_id
            FROM vehicles v
            JOIN personal_info pi ON pi.id = v.personal_info_id
            JOIN guests g ON pi.id = g.personal_info_id
            WHERE v.license_plate_number = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
            """,
            (license_plate_number, gate_id)
        )
        guest_data = cur.fetchone()

        if not guest_data:
            return _error_response(400, "Guest vehicle not found")

        other_info = guest_data["other_info"] or {}
        entry_window = other_info.get("entry_window", {})
        start_str = entry_window.get("start")
        end_str = entry_window.get("end")

        # If we cannot find a valid entry window, return an error
        if not (start_str and end_str):
            return _error_response(400, "No valid entry window found for this guest.")

        # Convert the start and end strings to datetime objects
        try:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = datetime.fromisoformat(end_str)
        except ValueError:
            return _error_response(400, "Invalid date format in entry window.")

        # Check if the current time is within [start_dt, end_dt]
        if not (start_dt <= now <= end_dt):
            return _error_response(400, "Guest cannot enter at this time (not yet valid or expired).")

        # Remove the 'otp' and 'entry_window' entries
        other_info.pop('otp', None)
        other_info.pop('entry_window', None)

        # Update the guest status and other_info
        cur.execute(
            """
                UPDATE guests
                SET status = 'CHECKED_IN', other_info = %s
                WHERE id = %s
                RETURNING id
            """,
            (json.dumps(other_info), guest_data["id"])
        )
        
        updated_row = cur.fetchone()
        if not updated_row:
            return _error_response(400, "Guest does not exist or could not be updated.")
        
        log(conn, "GUEST_VEHICLE_ARRIVAL", f"Guest '{guest_data['id']}' [{guest_data['name']}] arrived with vehicle license plate '{guest_data['license_plate_number']}'", None, guest_data["creator_id"], guest_data["estate_id"])
        # Commit the changes
        conn.commit()

    return _success_response(
        200,
        {
            "message": "Gate opened for guest",
            "guest_name": guest_data["name"]
        }
    )

def update_guest(conn, body, event):
    """
    Updates guest details, including personal_info attributes. Only allowed by the creator.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    guest_id = body.get("guest_id")
    
    # Guest fields
    expiry = body.get("expiry")
    other_info = body.get("other_info")

    # Personal Info fields
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    access_group_id = body.get("access_group_id")

    if not guest_id:
        return _error_response(400, "Missing 'guest_id'.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM guests g
                            JOIN personal_info pi ON g.personal_info_id = pi.id
                            WHERE g.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, guest_id))
        
        if not (cur.fetchone()[0] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""SELECT g.personal_info_id FROM guests g 
                        JOIN account_holders ah ON ah.id = g.creator_id 
                        WHERE g.id = %s AND ah.user_id = %s""", (guest_id, user_id))
            row = cur.fetchone()
            if not row:
                return _error_response(403, "You do not have privileges to update this guest.")
            personal_info_id = row[0]        

        # Update guest table
        cur.execute("""
            UPDATE guests
            SET other_info = COALESCE(%s, other_info)
            WHERE id = %s
            RETURNING creator_id
        """, (json.dumps(other_info) if other_info else None, guest_id))

        guest_data = cur.fetchone()

        if not guest_data:
            return _error_response(404, "Guest not found.")

        # Update personal_info table
        cur.execute("""
            UPDATE personal_info
            SET name = COALESCE(%s, name),
                id_type = COALESCE(%s, id_type),
                id_num = COALESCE(%s, id_num),
                contact = COALESCE(%s, contact),
                expiry = COALESCE(%s, expiry),
                access_group_id = COALESCE(%s, access_group_id)
            WHERE id = %s
            RETURNING estate_id
        """, (name, id_type, id_num, contact, expiry, access_group_id, personal_info_id))

        guest_info_data = cur.fetchone()

        log(conn, "GUEST_UPDATE", f"Guest '{guest_id}' [{name}] updated", user_id, guest_data[0], guest_info_data[0])

        conn.commit()

    return _success_response(200, {"message": "Guest and personal info updated successfully."})

def delete_guest(conn, body, event):
    """
    Deletes a guest and their associated personal_info, only allowed by the creator.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    guest_id = body.get("guest_id")

    if not guest_id:
        return _error_response(400, "Missing 'guest_id' or 'account_holder_id'.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM guests g
                            JOIN personal_info pi ON g.personal_info_id = pi.id
                            WHERE g.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, guest_id))
        
        if not (cur.fetchone()[0] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""SELECT g.personal_info_id, g.creator_id FROM guests g 
                        JOIN account_holders ah ON ah.id = g.creator_id 
                        WHERE g.id = %s AND ah.user_id = %s""", (guest_id, user_id))
            row = cur.fetchone()
            if not row:
                return _error_response(403, "You do not have privileges to delete this guest.")
            personal_info_id = row[0] 

        personal_info_id = row[0]

        # Delete personal_info entry which would cascade delete the guest
        cur.execute("DELETE FROM personal_info WHERE id = %s RETURNING name, estate_id", (personal_info_id,))
        result = cur.fetchone()
        if not result:
            return _error_response(404, "Guest not found.")
        
        log(conn, "GUEST_DELETION", f"Guest '{guest_id}' [{result[0]}] deleted", user_id, row[1], result[1])

        conn.commit()

    return _success_response(200, {"message": "Guest and personal info deleted successfully."})

def get_guest_details(conn, event):
    """
    Retrieves details of a specific guest, including their personal info.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    guest_id = path_params.get("guest_id")

    if not guest_id:
        return _error_response(400, "Missing 'guest_id'.")
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM guests g
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE g.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, guest_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the user
            cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM guests g
                            JOIN account_holders ah ON ah.id = g.creator_id
                            WHERE g.id = %s AND ah.user_id = %s
                        ) AS exists_flag
                        """, (guest_id, user_id))
            
            row = cur.fetchone()
            if not row:
                return _error_response(403, "You do not have privileges to delete this guest.")
            
        cur.execute("""
            SELECT g.id AS guest_id, g.personal_info_id, es.name AS estate_name, at.name AS account_type_name, ag.name AS access_group_name, pi.name AS guest_name, pi.contact, pi.expiry, pi.estate_id, g.other_info
            FROM guests g
            JOIN personal_info pi ON g.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            WHERE g.id = %s
        """, (guest_id,))
        guest = cur.fetchone()

    if not guest:
        return _error_response(404, "Guest not found.")

    return _success_response(200, {"guest": process_db_results([guest])})

def get_account_holder_guests(conn, event):
    """
    Lists all guests created by a specific account holder.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    account_holder_id = event.get("pathParameters", {}).get("account_holder_id")

    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("SELECT EXISTS(SELECT 1 FROM account_holders WHERE user_id = %s AND id = %s) AS exists_flag", (user_id, account_holder_id))
            row = cur.fetchone()
            if not row:
                return _error_response(403, "You do not have privileges to delete this guest.")
            
        cur.execute("""
            SELECT 
                g.id AS guest_id, 
                pi.name AS guest_name, 
                g.personal_info_id,
                pi.contact, 
                pi.expiry, 
                at.name AS account_type_name, 
                ag.name AS access_group_name, 
                g.other_info
            FROM guests g
            JOIN personal_info pi ON g.personal_info_id = pi.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            WHERE g.creator_id = %s
        """, (account_holder_id,))
        guests = cur.fetchall()

    return _success_response(200, {"guests": process_db_results(guests)})

def get_estate_guests(conn, event):
    """
    Lists all guests created by a specific estate.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    estate_id = event.get("pathParameters", {}).get("estate_id")

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
                        WHERE ah.user_id = %s AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                    ) AS has_privileges
                    """, (user_id, estate_id))

        if not (cur.fetchone()["has_privileges"] or is_admin):
            return _error_response(403, "You do not have privileges to get estate guests.")

        cur.execute("""
            SELECT 
                g.id AS guest_id, 
                pi.name AS guest_name, 
                g.personal_info_id,
                pi.contact, 
                pi.expiry, 
                at.name AS account_type_name, 
                ag.name AS access_group_name, 
                g.other_info,
                cpi.name AS creator_name,
                g.creator_id
            FROM guests g
            JOIN personal_info pi ON g.personal_info_id = pi.id
            JOIN account_holders ah ON ah.id = g.creator_id
            JOIN personal_info cpi ON ah.personal_info_id = cpi.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            WHERE cpi.estate_id = %s
        """, (estate_id,))
        guests = cur.fetchall()

    return _success_response(200, {"guests": process_db_results(guests)})

