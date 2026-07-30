import json
import random
from psycopg2.extras import RealDictCursor
from datetime import datetime
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, send_message, log, get_user_privileges
from middleware import verify_token, cors_wrap

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

def create_guest_regular(conn, body, event):
    """
    Registers a new guest under an account holder and creates a corresponding personal_info entry.
    All operations are performed in a single transaction.
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

    # Vehicle fields (optional)
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start = start if start else now
    other_info["entry_window"] = {
        "start": start,
        "end": expiry
    }

    if not all([account_holder_id, name, id_type, id_num, contact, expiry]):
        return _error_response(400, "Missing required fields.")

    # Check if vehicle info is provided
    if license_plate_number and not all([make, model, color]):
        return _error_response(400, "If license plate is provided, make, model, and color are required.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check privileges using helper
            privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

            if not privileges.is_valid:
                return _error_response(400, "No estate found for this account holder.")

            if not privileges.can_create_guests():
                return _error_response(403, "You do not have privileges to create a guest for this account.")

            estate_id = privileges.estate_id
            estate_name = privileges.estate_name

            # Create personal_info entry
            cur.execute("""
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, expiry, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name = 'GUEST'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
                RETURNING id
            """, (estate_id, name, id_type, id_num, contact, expiry, estate_id))
            personal_info_id = cur.fetchone()["id"]

            # Handle vehicle creation if license plate is provided
            if license_plate_number:
                # Check for vehicle privileges using helper
                if not privileges.can_create_vehicles():
                    conn.rollback()
                    return _error_response(403, "You do not have privileges to create a vehicle for this guest.")

                # Create vehicle (removed duplicate license plate check)
                cur.execute("""
                    INSERT INTO vehicles (personal_info_id, license_plate_number, make, model, color)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (personal_info_id, license_plate_number, make, model, color))

                vehicle_id = cur.fetchone()["id"]
                other_info["purpose"] = "visit_with_car"
                other_info["vehicle_id"] = vehicle_id
            else:
                # Generate OTP if guest has no car
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

            log(conn, "GUEST_CREATION", f"Guest {name} created.")#, user_id, account_holder_id, estate_id)

            conn.commit()

            expiry_date_readable = datetime.fromisoformat(expiry).strftime("%A, %d %B %Y at %H:%M")
            start_date_readable = datetime.fromisoformat(start).strftime("%A, %d %B %Y at %H:%M")

            phone_number = contact.lstrip('+')
            if license_plate_number:
                # Send invite message for guest with car
                send_message(
                    phone_number,
                    f"Hi {name},\nYou are invited to {estate_name}. Your access is valid from {start_date_readable} to {expiry_date_readable}. Please use the car entry lane."
                )
            else:
                # Send OTP message for guest without car
                send_message(phone_number, f"Hi {name},\nYour One Time Password (OTP) for your visit at {estate_name} is {otp}, valid from {start_date_readable} to {expiry_date_readable}")

            print(f"Window Opens: {start_date_readable}, Window Closes:{expiry_date_readable}")

        return _success_response(201, {"message": "Guest registered successfully.", "guest_id": guest_id, "personal_info_id": personal_info_id})

    except Exception as e:
        conn.rollback()
        return _error_response(500, f"Error creating guest: {str(e)}")

def create_associate(conn, body, event):
    """
    Registers a new associate under an account holder and creates a corresponding personal_info entry.
    All operations are performed in a single transaction.
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

    # Vehicle fields (optional)
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start = start if start else now
    other_info["entry_window"] = {
        "start": start,
        "end": expiry
    }

    if not all([account_holder_id, name, id_type, id_num, contact, expiry, account_type_id]):
        return _error_response(400, "Missing required fields.")

    # Check if vehicle info is provided
    if license_plate_number and not all([make, model, color]):
        return _error_response(400, "If license plate is provided, make, model, and color are required.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check privileges using helper
            privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

            if not privileges.is_valid:
                return _error_response(400, "No estate found for this account holder.")

            if not privileges.can_create_guests():
                return _error_response(403, "You do not have privileges to create an associate for this account.")

            estate_id = privileges.estate_id
            estate_name = privileges.estate_name

            # Create personal_info entry
            cur.execute("""
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, expiry, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
                RETURNING id
            """, (estate_id, name, id_type, id_num, contact, expiry, account_type_id, estate_id))
            personal_info_id = cur.fetchone()["id"]

            # Handle vehicle creation if license plate is provided
            if license_plate_number:
                # Check for vehicle privileges using helper
                if not privileges.can_create_vehicles():
                    conn.rollback()
                    return _error_response(403, "You do not have privileges to create a vehicle for this associate.")

                # Create vehicle (removed duplicate license plate check)
                cur.execute("""
                    INSERT INTO vehicles (personal_info_id, license_plate_number, make, model, color)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (personal_info_id, license_plate_number, make, model, color))

                vehicle_id = cur.fetchone()["id"]
                other_info["purpose"] = "visit_with_car"
                other_info["vehicle_id"] = vehicle_id
            else:
                # Generate OTP if associate has no car
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

            log(conn, "GUEST_CREATION", f"Guest {name} created.")#, user_id, account_holder_id, estate_id)

            conn.commit()

            expiry_date_readable = datetime.fromisoformat(expiry).strftime("%A, %d %B %Y %H:%M:%S")
            start_date_readable = datetime.fromisoformat(start).strftime("%A, %d %B %Y %H:%M:%S")

            phone_number = contact.lstrip('+')
            if license_plate_number:
                # Send invite message for associate with car
                send_message(
                    phone_number,
                    f"Hi {name},\nYou are invited to {estate_name}. Your access is valid from {start_date_readable} to {expiry_date_readable}. Please use the car entry lane."
                )
            else:
                # Send OTP message for associate without car
                send_message(phone_number, f"Hi {name},You are invited to {estate_name}.\nYour One Time Password (OTP) is {otp}, valid from {start_date_readable} to {expiry_date_readable}")

            print(f"Window Opens: {start_date_readable}, Window Closes:{expiry_date_readable}")

        return _success_response(201, {"message": "Guest registered successfully.", "guest_id": guest_id, "personal_info_id": personal_info_id})

    except Exception as e:
        conn.rollback()
        return _error_response(500, f"Error creating associate: {str(e)}")

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
        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_manage_guests():
            # Verify the guest belongs to the account holder
            cur.execute("""SELECT g.personal_info_id FROM guests g
                        JOIN account_holders ah ON ah.id = g.creator_id
                        WHERE g.id = %s AND ah.user_id = %s AND ah.is_active = TRUE""", (guest_id, user_id))
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
        
        log(conn, "GUEST_OTP_SENT", f"OTP sent to guest {guest_data['name']}.")#, user_id, account_holder_id, estate_id)

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
            SELECT pi.name, g.id, g.other_info, pi.estate_id, g.creator_id, ah.user_id AS inviter_user_id
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
        
        log(conn, "GUEST_OTP_VERIFIED", f"OTP verified by guest {guest_data['name']}.")#, None, guest_data["creator_id"], guest_data["estate_id"])

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


def update_guest(conn, body, event):
    """
    Updates guest details, including personal_info attributes and vehicle operations.
    Supports creating, updating, or removing vehicles as part of the guest update.
    Uses the same API structure as create_guest_regular for consistency.
    Only allowed by the creator or users with MANAGE_GUESTS privilege.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    # Extract fields using the same pattern as create_guest_regular
    guest_id = body.get("guest_id")
    account_holder_id = body.get("account_holder_id")  # Now consistent with create API
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    expiry = body.get("expiry")
    start = body.get("start", None)
    other_info = body.get("other_info", {})

    # Vehicle fields (optional) - same as create_guest_regular
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    # Handle entry window using the same logic as create_guest_regular
    # Only set entry_window if expiry is provided (like create_guest_regular)
    if expiry is not None:
        # Default 'start' to now if not provided (same as create_guest_regular)
        if start is None:
            start = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # Set entry_window (consistent with create_guest_regular)
        other_info["entry_window"] = {
            "start": start,
            "end": expiry
        }

    # Validate required fields - guest_id is required for updates
    if not guest_id:
        return _error_response(400, "Missing 'guest_id'.")

    # Check if vehicle info is provided (same validation as create_guest_regular)
    if license_plate_number and not all([make, model, color]):
        return _error_response(400, "If license plate is provided, make, model, and color are required.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # First get the guest's creator (account_holder_id), personal_info_id, and existing vehicle info
            cur.execute("""
                SELECT g.creator_id, g.personal_info_id, g.other_info,
                       v.id as vehicle_id, v.license_plate_number, v.make, v.model, v.color,
                       pi.estate_id, pi.contact as current_contact
                FROM guests g
                JOIN personal_info pi ON g.personal_info_id = pi.id
                LEFT JOIN vehicles v ON v.personal_info_id = g.personal_info_id
                WHERE g.id = %s
            """, (guest_id,))

            guest_info = cur.fetchone()
            if not guest_info:
                return _error_response(404, "Guest not found.")

            # Use account_holder_id from body if provided, otherwise use the existing creator_id
            # This allows for consistency with create API while maintaining backward compatibility
            if account_holder_id is None:
                account_holder_id = guest_info["creator_id"]
            else:
                # If account_holder_id is provided, verify it matches the existing creator
                if account_holder_id != guest_info["creator_id"]:
                    return _error_response(403, "This guest does not belong to the specified account holder.")

            personal_info_id = guest_info["personal_info_id"]
            existing_vehicle_id = guest_info["vehicle_id"]
            estate_id = guest_info["estate_id"]
            current_other_info = guest_info["other_info"] or {}
            current_contact = guest_info["current_contact"]

            # Check privileges using helper (same pattern as create_guest_regular)
            privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

            if not privileges.is_valid:
                return _error_response(400, "No estate found for this account holder.")

            # Allow if user has manage_guests (estate-wide) or owns this guest (create_guests + is_same_person)
            if not privileges.can_manage_or_own_guests():
                return _error_response(403, "You do not have privileges to update this guest.")

            # Handle vehicle operations using the same logic as create_guest_regular
            estate_name = privileges.estate_name

            # Start with current other_info and merge with provided other_info
            updated_other_info = current_other_info.copy()
            if other_info:
                updated_other_info.update(other_info)

            # Determine vehicle operation based on provided data
            vehicle_data_provided = license_plate_number or make or model or color
            has_existing_vehicle = existing_vehicle_id is not None

            # Handle vehicle creation if license plate is provided (same pattern as create_guest_regular)
            if license_plate_number:
                # Check for vehicle privileges using helper (same as create)
                if not privileges.can_create_vehicles():
                    return _error_response(403, "You do not have privileges to create/update a vehicle for this guest.")

                if has_existing_vehicle:
                    # UPDATE EXISTING VEHICLE
                    cur.execute("""
                        UPDATE vehicles
                        SET license_plate_number = COALESCE(%s, license_plate_number),
                            make = COALESCE(%s, make),
                            model = COALESCE(%s, model),
                            color = COALESCE(%s, color)
                        WHERE id = %s
                    """, (license_plate_number, make, model, color, existing_vehicle_id))
                    vehicle_id = existing_vehicle_id
                else:
                    # CREATE NEW VEHICLE (same as create_guest_regular)
                    cur.execute("""
                        INSERT INTO vehicles (personal_info_id, license_plate_number, make, model, color)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """, (personal_info_id, license_plate_number, make, model, color))
                    vehicle_id = cur.fetchone()["id"]

                # Set vehicle-related other_info (same as create_guest_regular)
                updated_other_info["purpose"] = "visit_with_car"
                updated_other_info["vehicle_id"] = vehicle_id
                # Remove OTP if it exists (guest now has car)
                updated_other_info.pop("otp", None)

            elif not vehicle_data_provided and has_existing_vehicle:
                # REMOVE EXISTING VEHICLE AND GENERATE OTP (only if explicitly removing vehicle)
                # This happens when no vehicle data is provided but guest currently has a vehicle
                if not privileges.can_create_vehicles():
                    return _error_response(403, "You do not have privileges to remove the vehicle for this guest.")

                # Delete vehicle
                cur.execute("DELETE FROM vehicles WHERE id = %s", (existing_vehicle_id,))

                # Generate new OTP (same pattern as create_guest_regular)
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

                updated_other_info["otp"] = otp
                updated_other_info["purpose"] = "visit"
                updated_other_info.pop("vehicle_id", None)

            elif not license_plate_number and not has_existing_vehicle:
                # NO VEHICLE SCENARIO - Generate OTP if guest doesn't have one (same as create_guest_regular)
                if "otp" not in updated_other_info:
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
                    updated_other_info["otp"] = otp
                    updated_other_info["purpose"] = "visit"

            # Update guest table
            cur.execute("""
                UPDATE guests
                SET other_info = %s
                WHERE id = %s
                RETURNING creator_id
            """, (json.dumps(updated_other_info), guest_id))

            guest_data = cur.fetchone()
            if not guest_data:
                return _error_response(404, "Guest not found.")

            # Update personal_info table
            # Note: access_group_id is not updated - guests always stay in 'REGULAR' access group
            cur.execute("""
                UPDATE personal_info
                SET name = COALESCE(%s, name),
                    id_type = COALESCE(%s, id_type),
                    id_num = COALESCE(%s, id_num),
                    contact = COALESCE(%s, contact),
                    expiry = COALESCE(%s, expiry)
                WHERE id = %s
                RETURNING estate_id
            """, (name, id_type, id_num, contact, expiry, personal_info_id))

            guest_info_data = cur.fetchone()

            # Get final contact info (use updated contact or existing)
            final_contact = contact if contact else current_contact

            log(conn, "GUEST_UPDATE", f"Guest {name or 'Unknown'} updated.")#, user_id, guest_data["creator_id"], guest_info_data["estate_id"])

            conn.commit()

            # Send notification messages using the same pattern as create_guest_regular
            if final_contact and expiry is not None:
                try:
                    # Get current entry window from updated_other_info
                    entry_window = updated_other_info.get("entry_window", {})
                    current_start = entry_window.get("start")
                    current_expiry = entry_window.get("end")

                    if current_start and current_expiry:
                        expiry_date_readable = datetime.fromisoformat(current_expiry).strftime("%A, %d %B %Y %H:%M:%S")
                        start_date_readable = datetime.fromisoformat(current_start).strftime("%A, %d %B %Y %H:%M:%S")

                        phone_number = final_contact.lstrip('+')

                        # Determine final vehicle status
                        final_has_vehicle = "vehicle_id" in updated_other_info

                        if final_has_vehicle:
                            # Send updated invite message for guest with car (same pattern as create_guest_regular)
                            send_message(
                                phone_number,
                                f"Hi {name or 'Guest'},\nYour visit details have been updated. Your access to {estate_name} is valid from {start_date_readable} to {expiry_date_readable}. Please use the car entry lane."
                            )
                        else:
                            # Send updated OTP message for guest without car (same pattern as create_guest_regular)
                            otp_text = f"Your One Time Password (OTP) is {updated_other_info.get('otp')}, " if updated_other_info.get('otp') else ""
                            send_message(
                                phone_number,
                                f"Hi {name or 'Guest'},\nYour visit details have been updated. {otp_text}valid from {start_date_readable} to {expiry_date_readable}"
                            )
                except Exception as msg_error:
                    # Don't fail the update if messaging fails
                    print(f"Failed to send update message: {str(msg_error)}")

        return _success_response(200, {
            "message": "Guest and personal info updated successfully.",
            "guest_id": guest_id,
            "has_vehicle": "vehicle_id" in updated_other_info,
            "otp_generated": "otp" in updated_other_info,
            "entry_window_updated": expiry is not None
        })

    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred while updating guest: {str(e)}")

def delete_guest(conn, body, event):
    """
    Deletes a guest and their associated personal_info. Only the creator, estate managers, or an admin can delete.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    guest_id = body.get("guest_id")
    if not guest_id:
        return _error_response(400, "Missing 'guest_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # First get the guest's creator (account_holder_id) and personal_info_id
        cur.execute("""
            SELECT g.creator_id, g.personal_info_id
            FROM guests g
            WHERE g.id = %s
        """, (guest_id,))

        guest_info = cur.fetchone()
        if not guest_info:
            return _error_response(404, "Guest not found.")

        account_holder_id = guest_info["creator_id"]
        personal_info_id = guest_info["personal_info_id"]
        actor_id = account_holder_id

        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_guests (estate-wide) or owns this guest (create_guests + is_same_person)
        if not privileges.can_manage_or_own_guests():
            return _error_response(403, "You do not have privileges to delete this guest.")

        # Delete personal_info (guests table has ON DELETE CASCADE)
        cur.execute("""
            DELETE FROM personal_info
            WHERE id = %s
            RETURNING name, estate_id
        """, (personal_info_id,))
        result = cur.fetchone()
        if not result:
            return _error_response(404, "Personal info not found.")

        guest_name = result["name"]
        estate_id = result["estate_id"]

        log(conn, "GUEST_DELETION", f"Guest {guest_name} deleted.")#, user_id, actor_id, estate_id)

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
        # First get the guest's creator (account_holder_id)
        cur.execute("""
            SELECT g.creator_id
            FROM guests g
            WHERE g.id = %s
        """, (guest_id,))

        guest_info = cur.fetchone()
        if not guest_info:
            return _error_response(404, "Guest not found.")

        account_holder_id = guest_info["creator_id"]

        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_guests (estate-wide) or create_guests (ownership-based)
        if not privileges.can_manage_or_own_guests():
            return _error_response(403, "You do not have privileges to view this guest.")
            
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
    Lists all guests created by a specific account holder with pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    account_holder_id = event.get("pathParameters", {}).get("account_holder_id")

    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

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
        # Check privileges using helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        # Allow if user has manage_guests (estate-wide) or owns these guests (create_guests + is_same_person)
        if not privileges.can_manage_or_own_guests():
            return _error_response(403, "You do not have privileges to view this guest list.")

        # Count total guests
        cur.execute("SELECT COUNT(*) FROM guests WHERE creator_id = %s", (account_holder_id,))
        total = cur.fetchone()["count"]

        # Fetch guests paginated
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
            ORDER BY g.date_created DESC
            LIMIT %s OFFSET %s
        """, (account_holder_id, page_size, offset))

        guests = cur.fetchall()

    return _success_response(200, {
        "guests": process_db_results(guests),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

def get_estate_guests(conn, event):
    """
    Lists all guests created within a specific estate, with pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    estate_id = event.get("pathParameters", {}).get("estate_id")
    if not estate_id:
        return _error_response(400, "Missing 'estate_id'.")

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
        # Check privileges - simplified query for estate-level access
        if not is_admin:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s AND pi.estate_id = %s AND ah.is_active = TRUE AND
                          (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_GUESTS')
                ) AS has_privileges
            """, (user_id, estate_id))

            if not cur.fetchone()["has_privileges"]:
                return _error_response(403, "You do not have privileges to get estate guests.")

        # Total count
        cur.execute("""
            SELECT COUNT(*) FROM guests g
            JOIN account_holders ah ON ah.id = g.creator_id
            JOIN personal_info cpi ON ah.personal_info_id = cpi.id
            WHERE cpi.estate_id = %s
        """, (estate_id,))
        total = cur.fetchone()["count"]

        # Paginated guest list
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
            ORDER BY g.date_created DESC
            LIMIT %s OFFSET %s
        """, (estate_id, page_size, offset))
        
        guests = cur.fetchall()

    return _success_response(200, {
        "guests": process_db_results(guests),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

