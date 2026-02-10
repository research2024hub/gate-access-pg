import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges
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
        # Get account holder from personal_info to establish privilege context
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
            FROM personal_info pi
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            WHERE pi.id = %s
        """, (personal_info_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(400, "Personal info not found.")

        account_holder_id = result["account_holder_id"]

        # Check privileges using enhanced helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_manage_vehicle_for_person(cur, personal_info_id):
            return _error_response(403, "You do not have privileges to create a vehicle for this person.")
            
        cur.execute("""
                SELECT 
                EXISTS(SELECT 1 FROM vehicles v
                    JOIN personal_info pi ON v.personal_info_id = pi.id
                    WHERE pi.estate_id = (SELECT pi2.estate_id FROM personal_info pi2 WHERE pi2.id = %s)
                    AND v.license_plate_number = %s) as car_exists
                """, (personal_info_id, license_plate_number))
        
        result2 = cur.fetchone()
        
        if result2["car_exists"]:
                return _error_response(409, "This license plate has already been registered at this estate.")
            
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
        
        log(conn, "VEHICLE_CREATION", f"Vehicle plate {license_plate_number} created")

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
        # Get vehicle's personal_info_id first
        cur.execute("""
            SELECT personal_info_id FROM vehicles WHERE id = %s
        """, (vehicle_id,))

        vehicle_result = cur.fetchone()
        if not vehicle_result:
            return _error_response(404, "Vehicle not found.")

        vehicle_personal_info_id = vehicle_result["personal_info_id"]

        # Get account holder from personal_info to establish privilege context
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
            FROM personal_info pi
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            WHERE pi.id = %s
        """, (vehicle_personal_info_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(400, "Personal info not found.")

        account_holder_id = result["account_holder_id"]

        # Check privileges using enhanced helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_manage_vehicle_for_person(cur, vehicle_personal_info_id):
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
        
        log(conn, "VEHICLE_UPDATE", f"Vehicle plate {license_plate_number} updated.")# user_id, actor_id, estate_id)
        
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
        # Get vehicle's personal_info_id first
        cur.execute("""
            SELECT personal_info_id FROM vehicles WHERE id = %s
        """, (vehicle_id,))

        vehicle_result = cur.fetchone()
        if not vehicle_result:
            return _error_response(404, "Vehicle not found.")

        vehicle_personal_info_id = vehicle_result["personal_info_id"]

        # Get account holder from personal_info to establish privilege context
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
            FROM personal_info pi
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            WHERE pi.id = %s
        """, (vehicle_personal_info_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(400, "Personal info not found.")

        account_holder_id = result["account_holder_id"]

        # Check privileges using enhanced helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_manage_vehicle_for_person(cur, vehicle_personal_info_id):
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
        
        log(conn, "VEHICLE_DELETION", f"Vehicle plate {license_plate_number} deleted.")#, user_id, actor_id, estate_id)

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
        # Get vehicle's personal_info_id first
        cur.execute("""
            SELECT personal_info_id FROM vehicles WHERE id = %s
        """, (vehicle_id,))

        vehicle_result = cur.fetchone()
        if not vehicle_result:
            return _error_response(404, "Vehicle not found.")

        vehicle_personal_info_id = vehicle_result["personal_info_id"]

        # Get account holder from personal_info to establish privilege context
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
            FROM personal_info pi
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            WHERE pi.id = %s
        """, (vehicle_personal_info_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(400, "Personal info not found.")

        account_holder_id = result["account_holder_id"]

        # Check privileges using enhanced helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_view_vehicle_for_person(cur, vehicle_personal_info_id):
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
    Lists all vehicles belonging to a specific person, with optional pagination.
    Supports query parameters: ?page=1&page_size=20
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
        # Get account holder from personal_info to establish privilege context
        cur.execute("""
            SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
            FROM personal_info pi
            LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
            LEFT JOIN guests g ON pi.id = g.personal_info_id
            WHERE pi.id = %s
        """, (personal_info_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(400, "Personal info not found.")

        account_holder_id = result["account_holder_id"]

        # Check privileges using enhanced helper
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "No estate found for this account holder.")

        if not privileges.can_view_vehicle_for_person(cur, personal_info_id):
            return _error_response(403, "You do not have privileges to view vehicles for this person.")
        
        # Count total
        cur.execute("SELECT COUNT(*) FROM vehicles WHERE personal_info_id = %s", (personal_info_id,))
        total = cur.fetchone()["count"]

        # Fetch paginated vehicles
        cur.execute("""
            SELECT id, license_plate_number, make, model, color
            FROM vehicles
            WHERE personal_info_id = %s
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (personal_info_id, page_size, offset))
        
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

