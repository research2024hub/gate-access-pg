import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_access_group(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    name = body.get("name")
    estate_id = body.get("estate_id")

    if not all([name, estate_id]):
        return _error_response(400, "Missing 'estate_id' or 'name'.")
        
    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, estate_id))
        
        if not (cur.fetchone()[0] or is_admin):
            return _error_response(403, "You do not have privileges to manage access groups")
    
        cur.execute("""
            INSERT INTO access_groups (estate_id, name)
            VALUES (%s, %s)
            RETURNING id
        """, (estate_id, name.upper()))
        access_group_id = cur.fetchone()[0]

        log(conn, "ACCESS_GROUP_CREATION", f"Access group {access_group_id} [{name.upper()}] created", user_id, None, estate_id)

        conn.commit()

    return _success_response(201, {"message": "Access Group created successfully.", "access_group_id": access_group_id})


def update_access_group(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    access_group_id = body.get("id")
    name = body.get("name")

    if not (access_group_id and name):
        return _error_response(400, "Missing 'id' or 'name'.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (
                    SELECT estate_id FROM access_groups ag WHERE ag.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, access_group_id))
        
        if not (cur.fetchone()[0] or is_admin):
            return _error_response(403, "You do not have privileges to manage access groups")
        
        cur.execute("""
            UPDATE access_groups
            SET name = %s
            WHERE id = %s
            RETURNING estate_id
        """, (name.upper(), access_group_id))

        result = cur.fetchone()

        if not result:
            return _error_response(404, "Access Group not found.")
        
        log(conn, "ACCESS_GROUP_UPDATE", f"Access group {access_group_id} [{name.upper()}] updated", user_id, None, result[0])

        conn.commit()

    return _success_response(200, {"message": "Access Group updated successfully.", "access_group_id": access_group_id})


def delete_access_group(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    access_group_id = body.get("id")
    if not access_group_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor() as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (
                    SELECT estate_id FROM access_groups ag WHERE ag.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, access_group_id))
        
        if not (cur.fetchone()[0] or is_admin):
            return _error_response(403, "You do not have privileges to manage access groups")
        
        cur.execute("""
            DELETE FROM access_groups WHERE id = %s RETURNING name, estate_id
        """, (access_group_id,))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Access Group not found.")
        
        log(conn, "ACCESS_GROUP_UPDATE", f"Access group {access_group_id} [{result[0]}] updated", user_id, None, result[1])

        conn.commit()

    return _success_response(200, {"message": "Access Group deleted successfully."})


def get_access_groups(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve all access groups across all estates.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, date_created, date_updated FROM access_groups")
        access_groups = cur.fetchall()

    return _success_response(200, {"access_groups": process_db_results(access_groups)})


def get_access_group_by_id(conn, event):
    payload, error = verify_token(event)
    if error:
        return error

    access_group_id = event.get("pathParameters", {}).get("id")
    if not access_group_id:
        return _error_response(400, "Missing access group ID.")
    
    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete estates.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM access_groups WHERE id = %s
        """, (access_group_id,))
        access_group = cur.fetchone()
        if not access_group:
            return _error_response(404, "Access Group not found.")

    return _success_response(200, {"access_group": process_db_results([access_group])})

def get_access_group_by_estate(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    estate_id = event.get("pathParameters", {}).get("id")
    if not estate_id:
        return _error_response(400, "Missing estate ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, estate_id))
        
        if not (cur.fetchone()[0] or is_admin):
            return _error_response(403, "You do not have privileges to manage access groups")
        
        cur.execute("""
            SELECT id, name, estate_id, date_created, date_updated
            FROM access_groups WHERE estate_id = %s
        """, (estate_id,))
        access_group = cur.fetchone()
        if not access_group:
            return _error_response(404, "Access Group not found.")

    return _success_response(200, {"access_group": process_db_results([access_group])})
