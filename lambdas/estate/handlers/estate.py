import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_estate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can create estates.")

    name = body.get("name")
    location_coordinates = body.get("location_coordinates")

    if not name or not location_coordinates:
        return _error_response(400, "Missing 'name' or 'location_coordinates'.")

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO estates (name, location_coordinates)
            VALUES (%s, %s)
            RETURNING id
        """, (name, location_coordinates))
        estate_id = cur.fetchone()[0]

        # A TRIGGER AUTOMATICALLY ADDS A DEFAULT ACCESS GROUP FOR THE ESTATE, CALLED 'REGULAR'

        log(conn, "ESTATE_CREATION", f"Estate '{estate_id}' [{name}] created", user_id, None, estate_id)

        conn.commit()

    return _success_response(201, {"message": "Estate created successfully. Initial access group created", "estate_id": estate_id})


def update_estate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    estate_id = body.get("id")
    name = body.get("name")
    location_coordinates = body.get("location_coordinates")

    if not estate_id or not (name or location_coordinates):
        return _error_response(400, "Missing 'id' or update fields ('name' or 'location_coordinates').")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL')
                    ) AS exists_flag
                    """, (user_id, estate_id))
        
        if not (cur.fetchone()[0] or is_admin):
            return _error_response(403, "You do not have privileges to manage this estate")
        
        cur.execute("""
            UPDATE estates
            SET name = COALESCE(%s, name),
                location_coordinates = COALESCE(%s, location_coordinates),
                date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
        """, (name, location_coordinates, estate_id))
        if not cur.fetchone():
            return _error_response(404, "Estate not found.")
        
        log(conn, "ESTATE_UPDATE", f"Estate '{estate_id}' [{name}] updated", user_id, None, estate_id)
        
        conn.commit()

    return _success_response(200, {"message": "Estate updated successfully.", "estate_id": estate_id})


def delete_estate(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete estates.")

    estate_id = body.get("id")
    if not estate_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM estates WHERE id = %s RETURNING name
        """, (estate_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Estate not found.")
        
        log(conn, "ESTATE_DELETION", f"Estate '{estate_id}' [{result[0]}] updated", user_id, None, estate_id)

        conn.commit()

    return _success_response(200, {"message": "Estate deleted successfully."})


def get_estates(conn, event):
    """
    Retrieves all estates with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    # If needed in the future:
    # is_admin = payload.get("is_admin", False)
    # if not is_admin:
    #     return _error_response(403, "Access denied. Only admins can get estates.")

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
        cur.execute("SELECT COUNT(*) FROM estates")
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT id, name, location_coordinates, date_created, date_updated
            FROM estates
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))

        estates = cur.fetchall()

    return _success_response(200, {
        "estates": process_db_results(estates),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def get_estate_by_id(conn, event):
    """
    Retrieves a specific estate by its ID.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    # is_admin = payload.get("is_admin", False)
    # if not is_admin:
    #     return _error_response(403, "Access denied. Only admins can get estate by id.")

    estate_id = event.get("pathParameters", {}).get("id")
    if not estate_id:
        return _error_response(400, "Missing estate ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, location_coordinates, date_created, date_updated
            FROM estates WHERE id = %s
        """, (estate_id,))
        estate = cur.fetchone()
        if not estate:
            return _error_response(404, "Estate not found.")

    return _success_response(200, {"estate": process_db_results([estate])})
