import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_vehicle(conn, body, event):
    """
    Registers a new vehicle under a personal_info entry.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id = body.get("personal_info_id") # Added this because it could be for a guest
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    if not all([personal_info_id, license_plate_number, make, model, color]):
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
                            FROM personal_info pi
                            WHERE pi.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES' OR pv.name = 'CREATE_VEHICLES')
                    ) AS exists_flag
                    """, (user_id, personal_info_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""
                        SELECT 
                        EXISTS(SELECT 1 FROM guests g
                            JOIN account_holders ah ON ah.id = g.creator_id
                            WHERE ah.user_id = %s AND g.personal_info_id = %s) AS for_my_guest,
                        EXISTS(SELECT 1 FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.user_id = %s AND pi.id = %s) AS for_myself
                        """, 
                        (user_id, personal_info_id, user_id, personal_info_id,))

            # Instead of calling cur.fetchone() multiple times, do:
            result = cur.fetchone()  # This fetches the single row you need.

            if not (result["for_myself"] or result["for_my_guest"]):
                return _error_response(403, "You do not have privileges to create a vehicle for this person.")

        # Insert new vehicle
        cur.execute("""
            INSERT INTO vehicles (personal_info_id, license_plate_number, make, model, color)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (personal_info_id, license_plate_number, make, model, color))
        
        vehicle_id = cur.fetchone()["id"]

        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) AS actor_id, pi.estate_id
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            LEFT JOIN account_holders ah ON ah.personal_info_id = pi.id
            LEFT JOIN guests g ON g.personal_info_id = pi.id
            WHERE v.id = %s
        """, (vehicle_id,))

        result = cur.fetchone()
        actor_id = result["actor_id"]
        estate_id = result["estate_id"]
        
        log(conn, "VEHICLE_CREATION", f"Vehicle '{vehicle_id}' [{license_plate_number}] created", user_id, actor_id, estate_id)

        conn.commit()

    return _success_response(201, {"message": "Vehicle registered successfully.", "vehicle_id": vehicle_id})


def update_vehicle(conn, body, event):
    """
    Updates a vehicle's details. Owners and admins can update.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id = body.get("personal_info_id") # Added this because it could be for a guest
    vehicle_id = body.get("vehicle_id")
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    if not (vehicle_id and personal_info_id):
        return _error_response(400, "Missing 'vehicle_id' or 'personal_info_id'.")

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
                            FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            WHERE v.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES' OR pv.name = 'CREATE_VEHICLES')
                    ) AS exists_flag
                    """, (user_id, vehicle_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""
                        SELECT 
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN guests g ON g.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.id = g.creator_id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_my_guest,
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.personal_info_id = pi.id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_myself
                        """, 
                        (user_id, vehicle_id, user_id, vehicle_id,))

            # Instead of calling cur.fetchone() multiple times, do:
            result = cur.fetchone()  # This fetches the single row you need.

            if not (result["for_myself"] or result["for_my_guest"]):
                return _error_response(403, "You do not have privileges to update this vehicle.")

        # Update vehicle details
        cur.execute("""
            UPDATE vehicles
            SET license_plate_number = COALESCE(%s, license_plate_number),
                make = COALESCE(%s, make),
                model = COALESCE(%s, model),
                color = COALESCE(%s, color),
                date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
        """, (license_plate_number, make, model, color, vehicle_id))

        if not cur.fetchone():
            return _error_response(500, "Failed to update vehicle.")
        
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) AS actor_id, pi.estate_id
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            LEFT JOIN account_holders ah ON ah.personal_info_id = pi.id
            LEFT JOIN guests g ON g.personal_info_id = pi.id
            WHERE v.id = %s
        """, (vehicle_id,))

        result = cur.fetchone()
        actor_id = result["actor_id"]
        estate_id = result["estate_id"]
        
        log(conn, "VEHICLE_UPDATE", f"Vehicle '{vehicle_id}' [{license_plate_number}] updated", user_id, actor_id, estate_id)
        
        conn.commit()

    return _success_response(200, {"message": "Vehicle updated successfully."})


def delete_vehicle(conn, body, event):
    """
    Deletes a vehicle. Only the owner or an admin can delete it.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    vehicle_id = body.get("vehicle_id")

    if not (vehicle_id):
        return _error_response(400, "Missing 'vehicle_id'.")

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
                            FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            WHERE v.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES' OR pv.name = 'CREATE_VEHICLES')
                    ) AS exists_flag
                    """, (user_id, vehicle_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""
                        SELECT 
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN guests g ON g.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.id = g.creator_id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_my_guest,
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.personal_info_id = pi.id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_myself
                        """, 
                        (user_id, vehicle_id, user_id, vehicle_id,))
            # Instead of calling cur.fetchone() multiple times, do:
            result = cur.fetchone()  # This fetches the single row you need.

            if not (result["for_myself"] or result["for_my_guest"]):
                return _error_response(403, "You do not have privileges to delete this vehicle.")

        
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) AS actor_id, pi.estate_id, v.license_plate_number
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            LEFT JOIN account_holders ah ON ah.personal_info_id = pi.id
            LEFT JOIN guests g ON g.personal_info_id = pi.id
            WHERE v.id = %s
        """, (vehicle_id,))

        result = cur.fetchone()
        actor_id = result["actor_id"]
        estate_id = result["estate_id"]
        license_plate_number = result["license_plate_number"]
        
        # Delete vehicle
        cur.execute("DELETE FROM vehicles WHERE id = %s RETURNING id", (vehicle_id,))
        if not cur.fetchone():
            return _error_response(500, "Failed to delete vehicle.")
        
        log(conn, "VEHICLE_DELETION", f"Vehicle '{vehicle_id}' [{license_plate_number}] deleted", user_id, actor_id, estate_id)

        conn.commit()

    return _success_response(200, {"message": "Vehicle deleted successfully."})


def get_vehicle_details(conn, event):
    """
    Retrieves details of a specific vehicle.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    vehicle_id = path_params.get("vehicle_id")

    if not vehicle_id:
        return _error_response(400, "Missing 'vehicle_id'.")

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
                            FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            WHERE v.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES' OR pv.name = 'CREATE_VEHICLES')
                    ) AS exists_flag
                    """, (user_id, vehicle_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""
                        SELECT 
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN guests g ON g.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.id = g.creator_id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_my_guest,
                        EXISTS(SELECT 1 FROM vehicles v
                            JOIN personal_info pi ON v.personal_info_id = pi.id
                            JOIN account_holders ah ON ah.personal_info_id = pi.id
                            WHERE ah.user_id = %s AND v.id = %s) AS for_myself
                        """, 
                        (user_id, vehicle_id, user_id, vehicle_id,))
            # Instead of calling cur.fetchone() multiple times, do:
            result = cur.fetchone()  # This fetches the single row you need.

            if not (result["for_myself"] or result["for_my_guest"]):
                return _error_response(403, "You do not have privileges to get information about this vehicle")
            
        cur.execute("""
            SELECT v.id, v.license_plate_number, v.make, v.model, v.color, pi.name AS owner_name, pi.contact
            FROM vehicles v
            JOIN personal_info pi ON v.personal_info_id = pi.id
            WHERE v.id = %s
        """, (vehicle_id,))
        
        vehicle = cur.fetchone()
        if not vehicle:
            return _error_response(404, "Vehicle not found.")

    return _success_response(200, {"vehicle": process_db_results([vehicle])})  # 🚀 Removed unnecessary list wrapping


def list_vehicles_by_owner(conn, event):
    """
    Lists all vehicles belonging to a specific person.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    personal_info_id = path_params.get("personal_info_id")

    if not personal_info_id:
        return _error_response(400, "Missing 'personal_info_id'.")

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
                            FROM personal_info pi
                            WHERE pi.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES' OR pv.name = 'CREATE_VEHICLES')
                    ) AS exists_flag
                    """, (user_id, personal_info_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""
                        SELECT 
                        EXISTS(SELECT 1 FROM personal_info pi
                            JOIN account_holders ah ON ah.personal_info_id = pi.id
                            WHERE ah.user_id = %s AND pi.id = %s) AS for_myself
                        """, 
                        (user_id, personal_info_id))
            # Instead of calling cur.fetchone() multiple times, do:
            result = cur.fetchone()  # This fetches the single row you need.

            # Then use the same result as needed:
            if not (result["for_myself"]):
                return _error_response(403, "You do not have privileges to create a vehicle for this person.")
            
        cur.execute("""
            SELECT id, license_plate_number, make, model, color
            FROM vehicles
            WHERE personal_info_id = %s
        """, (personal_info_id,))
        
        vehicles = cur.fetchall()

    return _success_response(200, {"vehicles": process_db_results(vehicles)})
