import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_privilege(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can create privileges.")

    name = body.get("name")

    if not name:
        return _error_response(400, "Missing 'name'.")

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO privileges (name)
            VALUES (%s)
            RETURNING id
        """, (name.upper(),))
        privilege_id = cur.fetchone()[0]

        log(conn, "PRIVILEGE_CREATION", f"Privilege '{privilege_id}' [{name}] created", user_id, None, None)

        conn.commit()

    return _success_response(201, {"message": "Privilege created successfully.", "privilege_id": privilege_id})

def update_privilege(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can update privileges.")

    privilege_id = body.get("id")
    name = body.get("name")

    if not privilege_id or not name:
        return _error_response(400, "Missing 'id' or 'name'.")

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE privileges
            SET name = %s, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
        """, (name.upper(), privilege_id))
        if not cur.fetchone():
            return _error_response(404, "Privilege not found.")
        
        log(conn, "PRIVILEGE_UDATE", f"Privilege '{privilege_id}' [{name}] updated", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Privilege updated successfully.", "privilege_id": privilege_id})

def delete_privilege(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete privileges.")

    privilege_id = body.get("id")
    if not privilege_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM privileges WHERE id = %s RETURNING name
        """, (privilege_id,))

        result = cur.fetchone()

        if not result:
            return _error_response(404, "Privilege not found.")
        
        log(conn, "PRIVILEGE_DELETION", f"Privilege '{privilege_id}' [{result[0]}] deletion", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Privilege deleted successfully."})


def get_privileges(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can get privileges.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, date_created, date_updated FROM privileges")
        privileges = cur.fetchall()

    return _success_response(200, {"privileges": process_db_results(privileges)})


def get_privilege_by_id(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can get privileges.")

    privilege_id = event.get("pathParameters", {}).get("id")
    if not privilege_id:
        return _error_response(400, "Missing privilege ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM privileges WHERE id = %s
        """, (privilege_id,))
        privilege = cur.fetchone()
        if not privilege:
            return _error_response(404, "Privilege not found.")

    return _success_response(200, {"privilege": process_db_results([privilege])})
