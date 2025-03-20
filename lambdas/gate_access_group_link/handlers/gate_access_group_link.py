import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def create_access_group_link(conn, body, event):
    """
    Assigns an access group to a gate after verifying both exist.
    Allows optional opening_time and closing_time.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("gate_id")
    access_group_id = body.get("access_group_id")
    opening_time = body.get("opening_time")  # Optional
    closing_time = body.get("closing_time")  # Optional

    if not gate_id or not access_group_id:
        return _error_response(400, "Missing 'gate_id' or 'access_group_id'.")

    with conn.cursor() as cur:
        # Verify that the gate and access group exist and belong to the same estate
        cur.execute("""
            SELECT 
                (SELECT estate_id FROM gates WHERE id = %s) AS gate_estate,
                (SELECT estate_id FROM access_groups WHERE id = %s) AS access_group_estate
        """, (gate_id, access_group_id))
        result = cur.fetchone()

        gate_estate = result[0]
        access_group_estate = result[1]

        if gate_estate is None:
            return _error_response(404, "Gate not found.")
        if access_group_estate is None:
            return _error_response(404, "Access group not found.")

        if gate_estate != access_group_estate:
            return _error_response(400, "Estate mismatch. Gate and access group belong to different estates.")
        
        # Check user privileges
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s 
                AND pi.estate_id = %s 
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
            ) AS exists_flag
        """, (user_id, gate_estate))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage access group links.")

        # Insert the new link, including optional opening and closing times
        cur.execute("""
            INSERT INTO gate_access_group_links (gate_id, access_group_id, opening_time, closing_time)
            VALUES (%s, %s, COALESCE(%s, DEFAULT), COALESCE(%s, DEFAULT))
            ON CONFLICT (gate_id, access_group_id) DO NOTHING
            RETURNING gate_id, access_group_id
        """, (gate_id, access_group_id, opening_time, closing_time))

        if not cur.fetchone():
            return _error_response(409, "Access group already linked to this gate.")
        
        log(conn, "ACCESS_GROUP_GATE_LINK_CREATION", 
            f"Link between access group '{access_group_id}' and gate '{gate_id}' created with opening_time={opening_time} and closing_time={closing_time}", 
            user_id, None, gate_estate)

        conn.commit()

    return _success_response(201, {"message": "Access group linked successfully."})



def update_access_group_link(conn, body, event):
    """
    Updates an access group link to a gate, allowing changes to opening_time and closing_time.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("gate_id")
    access_group_id = body.get("access_group_id")
    opening_time = body.get("opening_time")  # Optional
    closing_time = body.get("closing_time")  # Optional

    if not gate_id or not access_group_id:
        return _error_response(400, "Missing 'gate_id' or 'access_group_id'.")

    with conn.cursor() as cur:
        # Verify the existing link and estates
        cur.execute("""
            SELECT 
                g.estate_id AS gate_estate,
                ag.estate_id AS access_group_estate
            FROM gate_access_group_links ggl
            JOIN gates g ON ggl.gate_id = g.id
            JOIN access_groups ag ON ggl.access_group_id = ag.id
            WHERE ggl.gate_id = %s AND ggl.access_group_id = %s
        """, (gate_id, access_group_id))

        result = cur.fetchone()
        if not result:
            return _error_response(404, "Link between gate and access group not found.")

        gate_estate, access_group_estate = result

        if gate_estate != access_group_estate:
            return _error_response(400, "Estate mismatch. Gate and access group belong to different estates.")

        # Check privileges
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s 
                AND pi.estate_id = %s 
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
            ) AS exists_flag
        """, (user_id, gate_estate))

        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to update access group links.")

        # Update only provided fields using COALESCE to retain existing values
        cur.execute("""
            UPDATE gate_access_group_links
            SET 
                opening_time = COALESCE(%s, opening_time),
                closing_time = COALESCE(%s, closing_time)
            WHERE gate_id = %s AND access_group_id = %s
            RETURNING gate_id, access_group_id
        """, (opening_time, closing_time, gate_id, access_group_id))

        if not cur.fetchone():
            return _error_response(404, "Access group link not found.")

        log(conn, "ACCESS_GROUP_GATE_LINK_UPDATE", 
            f"Link between access group '{access_group_id}' and gate '{gate_id}' updated: opening_time={opening_time} and closing_time={closing_time}", 
            user_id, None, gate_estate)

        conn.commit()

    return _success_response(200, {"message": "Access group link updated successfully."})


def remove_access_group_link(conn, body, event):
    """
    Removes an access group from a gate.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    gate_id = body.get("gate_id")
    access_group_id = body.get("access_group_id")

    if not gate_id or not access_group_id:
        return _error_response(400, "Missing 'gate_id' or 'access_group_id'.")

    with conn.cursor() as cur:   
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, gate_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage access group links")
        
        cur.execute("""
            DELETE FROM gate_access_group_links
            WHERE gate_id = %s AND access_group_id = %s
            RETURNING gate_id, access_group_id
        """, (gate_id, access_group_id))
        if not cur.fetchone():
            return _error_response(404, "Access group link not found.")
        
        cur.execute("""
            SELECT estate_id FROM gates WHERE id = %s
        """, (gate_id))
        result = cur.fetchone()
        
        log(conn, "ACCESS_GROUP_GATE_LINK_REMOVAL", f"Link between access group '{access_group_id}' and gate '{gate_id}' removed", user_id, None, result[0])

        conn.commit()

    return _success_response(200, {"message": "Access group removed successfully."})


def list_gate_access_groups(conn, event):
    """
    Lists all access groups linked to a gate (returns IDs and names).
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    gate_id = path_params.get("gate_id")

    if not gate_id:
        return _error_response(400, "Missing 'gate_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, gate_id))
        
        has_privileges = cur.fetchone()["exists_flag"]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to retrieve access groups related to this gate")
        
        cur.execute("""
            SELECT ag.id AS access_group_id, ag.name AS access_group_name
            FROM gate_access_group_links gag
            JOIN access_groups ag ON gag.access_group_id = ag.id
            WHERE gag.gate_id = %s
        """, (gate_id,))
        access_groups = cur.fetchall()

    return _success_response(200, {"access_groups": process_db_results(access_groups)})


def list_access_group_gates(conn, event):
    """
    Lists all gates linked to an access group (returns IDs and names).
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    access_group_id = path_params.get("access_group_id")

    if not access_group_id:
        return _error_response(400, "Missing 'access_group_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = (SELECT estate_id FROM access_groups WHERE id = %s) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCESS')
                    ) AS exists_flag
                    """, (user_id, access_group_id))
        
        has_privileges = cur.fetchone()["exists_flag"]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to retrieve gates for this access group")
        
        cur.execute("""
            SELECT g.id AS gate_id, g.name AS gate_name
            FROM gate_access_group_links gag
            JOIN gates g ON gag.gate_id = g.id
            WHERE gag.access_group_id = %s
        """, (access_group_id,))
        gates = cur.fetchall()

    return _success_response(200, {"gates": process_db_results(gates)})
