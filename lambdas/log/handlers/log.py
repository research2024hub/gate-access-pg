import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results
from middleware import verify_token

def get_logs_by_estate(conn, event):
    """
    Retrieves logs for a specific estate.
    Only admins can access this data.
    """
    payload, error = verify_token(event)
    if error:
        return 
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    if not payload.get("is_admin"):
        return _error_response(403, "Access denied. Only admins can view estate logs.")

    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")

    if not estate_id:
        return _error_response(400, "Missing 'estate_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM users u
                        JOIN account_holders ah ON u.id = ah.user_id
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE u.id = %s AND pi.estate_id = %s AND (pv.name = 'MANAGE_ALL' OR pv.name = 'VIEW_LOGS')
                    ) AS exists_flag
                    """, (user_id, estate_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            return _error_response(403, "You do not have privileges to retrieves logs for this estate.")
            
        cur.execute("""
            SELECT *
            FROM logs
            WHERE estate_id = %s
            ORDER BY date_created DESC
        """, (estate_id,))
        
        logs = cur.fetchall()

    return _success_response(200, {"estate_id": estate_id, "logs": process_db_results(logs)})

def get_logs_by_account_holder(conn, event):
    """
    Retrieves logs for a specific account holder.
    Only the account holder (linked via user_id) or an admin can access this data.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    account_holder_id = path_params.get("account_holder_id")

    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM users u
                        JOIN account_holders ah ON u.id = ah.user_id
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE u.id = %s AND pi.estate_id = ( 
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                        ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'VIEW_LOGS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            # Verify the guest belongs to the account holder and get personal_info_id
            cur.execute("""SELECT EXISTS(
                            SELECT 1 FROM account_holders 
                            WHERE user_id = %s AND id = %s
                        ) AS exists_flag""", (user_id, account_holder_id))
            if not cur.fetchone()["exists_flag"]:
                return _error_response(403, "You do not have privileges to logs for this account holder.")
            
        # Check if the user is an admin or owns the given account_holder_id
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders WHERE id = %s AND user_id = %s
            ) AS is_owner
        """, (account_holder_id, payload["user_id"]))

        row = cur.fetchone()
        is_owner = row["is_owner"] if row else False

        if not payload.get("is_admin") and not is_owner:
            return _error_response(403, "Access denied. You are not the owner of this account.")

        # Fetch logs for the requested account_holder_id
        cur.execute("""
            SELECT *
            FROM logs
            WHERE target_account_holder_id = %s OR actor_user_id = (
                SELECT user_id FROM account_holders WHERE id = %s
            )
            ORDER BY date_created DESC
        """, (account_holder_id, account_holder_id))
        
        logs = cur.fetchall()

    # if not logs:
    #     return _error_response(404, "No logs found for the specified account holder.")

    return _success_response(200, {"account_holder_id": account_holder_id, "logs": process_db_results(logs)})

