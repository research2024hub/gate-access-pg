from database import insert_row
import json
import os
from database import DictCursor
from utils import _error_response, _success_response, process_db_results, log
# from middleware import verify_token
import database



def get_db_conn():
    """Create and return a DB connection from DATABASE_URL env var."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        # raise RuntimeError("DATABASE_URL not set")
        return _error_response(500, "DATABASE_URL not set")
    return database.connect(db_url)

def create_vehicle(body,is_admin):
    """
    Registers a new vehicle under a personal_info entry.
    """
    # payload, error = verify_token(event)
    # if error:
    #     return error
    
    # user_id = payload.get("user_id")
    # is_admin = payload.get("is_admin", False)
    user_id = body.get("user_id")
    personal_info_id = body.get("personal_info_id") # Added this because it could be for a guest
    license_plate_number = body.get("license_plate_number")
    make = body.get("make")
    model = body.get("model")
    color = body.get("color")

    if not all([personal_info_id, license_plate_number, make, model, color]):
        return _error_response(400, "Missing required fields.")
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor(cursor=DictCursor) as cur:
            cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            JOIN account_types act ON pi.account_type_id = act.id
                            JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                            JOIN privileges pv ON atpl.privilege_id = pv.id
                            WHERE ah.is_active = TRUE AND ah.user_id = %s AND pi.estate_id = ( 
                                SELECT pi.estate_id 
                                FROM personal_info pi
                                WHERE pi.id = %s
                        ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_VEHICLES')
                        ) AS exists_flag
                        """, (user_id, personal_info_id))
            
            if not (cur.fetchone()["exists_flag"] or is_admin):
                # Verify the guest belongs to the account holder and get personal_info_id
                cur.execute("""
                            SELECT 
                            EXISTS(SELECT 1 FROM guests g
                                JOIN account_holders ah ON ah.id = g.creator_id
                                JOIN personal_info pi ON ah.personal_info_id = pi.id
                                JOIN account_types act ON pi.account_type_id = act.id
                                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                                JOIN privileges pv ON atpl.privilege_id = pv.id
                                WHERE ah.is_active = TRUE AND ah.user_id = %s AND g.personal_info_id = %s AND pv.name = 'CREATE_VEHICLES') AS for_my_guest,
                            EXISTS(SELECT 1 FROM account_holders ah
                                JOIN personal_info pi ON ah.personal_info_id = pi.id
                                JOIN account_types act ON pi.account_type_id = act.id
                                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                                JOIN privileges pv ON atpl.privilege_id = pv.id
                                WHERE ah.is_active = TRUE AND ah.user_id = %s AND pi.id = %s AND pv.name = 'CREATE_VEHICLES') AS for_myself
                            """, 
                            (user_id, personal_info_id, user_id, personal_info_id,))

                # Instead of calling cur.fetchone() multiple times, do:
                result = cur.fetchone()  # This fetches the single row you need.

                if not (result["for_myself"] or result["for_my_guest"]):
                    return _error_response(403, "You do not have privileges to create a vehicle for this person.")

            # Insert new vehicle (removed duplicate license plate check)
            _write_result = insert_row(cur, """
                INSERT INTO vehicles (personal_info_id, license_plate_number, make, model, color)
                VALUES (%s, %s, %s, %s, %s)
            """, (personal_info_id, license_plate_number, make, model, color), table='vehicles', columns='id')
            
            vehicle_id = _write_result["id"]

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
    except Exception as e:
        if conn:
            conn.rollback()
        return _error_response(500, f"Error creating vehicle: {str(e)}")
    finally:
        if conn:
            conn.close()