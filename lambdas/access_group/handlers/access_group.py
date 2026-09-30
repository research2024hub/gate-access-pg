from database import delete_row, insert_row, update_row
import json
from database import DictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, log, get_user_privileges_for_estate, get_user_privileges_for_access_group
from middleware import verify_token, cors_wrap

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

def create_access_group(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    name = body.get("name")
    estate_id = body.get("estate_id")

    if not all([name, estate_id]):
        return _error_response(400, "Missing 'estate_id' or 'name'.")
        
    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_access_groups():
            return _error_response(403, "You do not have privileges to manage access groups")

        _write_result = insert_row(cur, """
            INSERT INTO access_groups (estate_id, name)
            VALUES (%s, %s)
        """, (estate_id, name.upper()), table='access_groups', columns='id')
        access_group_id = _write_result["id"]

        log(conn, "ACCESS_GROUP_CREATION", f"Access group {access_group_id} [{name.upper()}] created", user_id, None, estate_id)

        conn.commit()

    return _success_response(201, {"message": "Access Group created successfully.", "access_group_id": access_group_id})


def update_access_group(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    access_group_id = body.get("id")
    name = body.get("name")

    if not (access_group_id and name):
        return _error_response(400, "Missing 'id' or 'name'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_access_group(cur, user_id, access_group_id, is_admin)

        if not privileges:
            return _error_response(403, "Access group not found or you do not have an account in this estate")

        if not privileges.can_manage_access_groups():
            return _error_response(403, "You do not have privileges to manage access groups")

        _write_result = update_row(cur, """
            UPDATE access_groups
            SET name = %s
            WHERE id = %s
        """, (name.upper(), access_group_id), table='access_groups', columns='estate_id', where='id = %s', where_count=1)

        result = _write_result

        if not result:
            return _error_response(404, "Access Group not found.")

        log(conn, "ACCESS_GROUP_UPDATE", f"Access group {access_group_id} [{name.upper()}] updated", user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Access Group updated successfully.", "access_group_id": access_group_id})


def delete_access_group(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    access_group_id = body.get("id")
    if not access_group_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_access_group(cur, user_id, access_group_id, is_admin)

        if not privileges:
            return _error_response(403, "Access group not found or you do not have an account in this estate")

        if not privileges.can_manage_access_groups():
            return _error_response(403, "You do not have privileges to manage access groups")

        _write_result = delete_row(cur, """
            DELETE FROM access_groups WHERE id = %s
        """, (access_group_id,), table='access_groups', columns='name, estate_id', where='id = %s', where_count=1)

        result = _write_result
        if not result:
            return _error_response(404, "Access Group not found.")

        log(conn, "ACCESS_GROUP_DELETION", f"Access group {access_group_id} [{result['name']}] deleted", user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Access Group deleted successfully."})


def get_access_groups(conn, event):
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve all access groups across all estates.")

    # Extract query parameters for pagination
    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError
    except ValueError:
        return _error_response(400, "Invalid 'page' or 'page_size' parameter.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor=DictCursor) as cur:
        # Get total count
        cur.execute("SELECT COUNT(*) AS count FROM access_groups")
        total_count = cur.fetchone()["count"]

        # Get paginated records
        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM access_groups
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))
        access_groups = cur.fetchall()

    return _success_response(200, {
        "access_groups": process_db_results(access_groups),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_count,
            "pages": (total_count + page_size - 1) // page_size
        }
    })


def get_access_group_by_id(conn, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    access_group_id = event.get("pathParameters", {}).get("id")
    if not access_group_id:
        return _error_response(400, "Missing access group ID.")
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete estates.")

    with conn.cursor(cursor=DictCursor) as cur:
        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM access_groups WHERE id = %s
        """, (access_group_id,))
        access_group = cur.fetchone()
        if not access_group:
            return _error_response(404, "Access Group not found.")

    return _success_response(200, {"access_group": process_db_results([access_group])})

def get_access_groups_by_estate(conn, event):
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    estate_id = event.get("pathParameters", {}).get("id")
    if not estate_id:
        return _error_response(400, "Missing estate ID.")

    # Handle pagination
    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError
    except ValueError:
        return _error_response(400, "Invalid 'page' or 'page_size' parameter.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_access_groups():
            return _error_response(403, "You do not have privileges to manage access groups.")

        # Count total access groups
        cur.execute("SELECT COUNT(*) AS count FROM access_groups WHERE estate_id = %s", (estate_id,))
        total = cur.fetchone()["count"]

        # Fetch paginated access groups
        cur.execute("""
            SELECT id, name, estate_id, date_created, date_updated
            FROM access_groups
            WHERE estate_id = %s
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (estate_id, page_size, offset))
        access_groups = cur.fetchall()

    return _success_response(200, {
        "access_groups": process_db_results(access_groups),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

