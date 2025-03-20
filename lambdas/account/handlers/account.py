import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token

def signup(conn, body):
    """
    Handles account creation for an existing user in a new estate.
    """
    user_id = body.get("user_id")
    estate_id = body.get("estate_id")
    house_address = body.get("house_address")

    # Validate required fields.
    if not user_id or not estate_id or not house_address:
        return _error_response(400, "Missing required fields: 'user_id', 'estate_id', or 'house_address'.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Prevent duplicate signup in the same estate.
            cur.execute("""
                SELECT id FROM account_holders
                WHERE user_id = %s AND personal_info_id IN (
                    SELECT id FROM personal_info WHERE estate_id = %s
                )
            """, (user_id, estate_id))
            if cur.fetchone():
                return _error_response(409, "User already has an account in this estate.")

            # Insert into personal_info.
            cur.execute("""
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name='USER_A'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
                RETURNING id
            """, (
                estate_id,
                body.get("name"),
                body.get("id_type"),
                body.get("id_num"),
                body.get("contact"),
                estate_id
            ))

            personal_info_row = cur.fetchone()
            if not personal_info_row:
                return _error_response(500, "Failed to create personal info.")
            personal_info_id = personal_info_row["id"]

            # Create account holder entry.
            cur.execute("""
                INSERT INTO account_holders (user_id, personal_info_id, house_address)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (user_id, personal_info_id, house_address))
            account_holder_row = cur.fetchone()
            if not account_holder_row:
                return _error_response(500, "Failed to create account holder.")
            account_holder_id = account_holder_row["id"]

            log(conn, "REGULAR_ACCOUNT_CREATION", "Resident account created", user_id, account_holder_id, estate_id,)

            conn.commit()

        return _success_response(201, {
            "message": "Signup successful.",
            "account": {
                "account_holder_id": account_holder_id,
                "personal_info_id": personal_info_id,
                "user_id": user_id,
                "estate_id": estate_id,
                "house_address": house_address
            }
        })
    
    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred: {e}")

def signupAdmin(conn, body):
    """
    Handles account creation for an existing user in a new estate.
    """
    user_id = body.get("user_id")
    estate_id = body.get("estate_id")
    house_address = body.get("house_address")

    # Validate required fields.
    if not user_id or not estate_id or not house_address:
        return _error_response(400, "Missing required fields: 'user_id', 'estate_id', or 'house_address'.")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Ensure user exists.
            # cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            # if not cur.fetchone():
            #     return _error_response(404, "User not found.")
            
            # cur.execute("SELECT id FROM estates WHERE id = %s", (estate_id,))
            # if not cur.fetchone():
            #     return _error_response(404, "Estate not found.")

            # Prevent duplicate signup in the same estate.
            cur.execute("""
                SELECT id FROM account_holders
                WHERE user_id = %s AND personal_info_id IN (
                    SELECT id FROM personal_info WHERE estate_id = %s
                )
            """, (user_id, estate_id))
            if cur.fetchone():
                return _error_response(409, "User already has an account in this estate.")

            # Insert into personal_info.
            cur.execute("""
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name='ADMIN'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
                RETURNING id
            """, (
                estate_id,
                body.get("name"),
                body.get("id_type"),
                body.get("id_num"),
                body.get("contact"),
                estate_id
            ))

            personal_info_row = cur.fetchone()
            if not personal_info_row:
                return _error_response(500, "Failed to create personal info.")
            personal_info_id = personal_info_row["id"]

            # Create account holder entry.
            cur.execute("""
                INSERT INTO account_holders (user_id, personal_info_id, house_address)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (user_id, personal_info_id, house_address))
            account_holder_row = cur.fetchone()
            if not account_holder_row:
                return _error_response(500, "Failed to create account holder.")
            account_holder_id = account_holder_row["id"]

            log(conn, "ADMIN_ACCOUNT_CREATION", "Admin account created", user_id, account_holder_id, estate_id)

            conn.commit()

        return _success_response(201, {
            "message": "Signup successful.",
            "account": {
                "account_holder_id": account_holder_id,
                "personal_info_id": personal_info_id,
                "user_id": user_id,
                "estate_id": estate_id,
                "house_address": house_address
            }
        })
    
    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred: {e}")

def change_account_type(conn, body, event):
    """
    Allows an admin to change an account holder's account type.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id = body.get("personal_info_id")
    account_type_id = body.get("account_type_id")

    if not personal_info_id or not account_type_id:
        return _error_response(400, "Missing 'personal_info_id' or 'account_type_id'.")

    with conn.cursor() as cur:
        # cur.execute("""
        #                 SELECT estate_id FROM personal_info
        #                 JOIN account_holders ah ON ah.personal_info
        #                 WHERE personal_info.id = %s
        #             """, (user_id, personal_info_id))
        # result = cur.fetchone()
        # Check if account type exists
        cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        JOIN account_types act ON pi.account_type_id = act.id
                        JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                        JOIN privileges pv ON atpl.privilege_id = pv.id
                        WHERE ah.user_id = %s AND pi.estate_id = ( 
                            SELECT estate_id FROM personal_info
                            WHERE personal_info.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                    ) AS exists_flag
                    """, (user_id, personal_info_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage accounts")
        
        cur.execute("SELECT id FROM account_types WHERE id = %s", (account_type_id,))
        if not cur.fetchone():
            return _error_response(404, "Account type not found.")

        # Proceed to update the account type in personal_info
        cur.execute("""
            UPDATE personal_info
            SET account_type_id = %s, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s RETURNING id
        """, (account_type_id, personal_info_id))
        
        if not cur.fetchone():
            return _error_response(404, "Personal info not found.")
        
        cur.execute("""
                    SELECT ah.id, pi.estate_id FROM account_holders ah 
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.personal_info_id = %s
                    """, (personal_info_id,))
        
        result = cur.fetchone()

        log(conn, "ACCOUNT_TYPE_CHANGE", "Account type changed", user_id, result[0], result[1])

        conn.commit()

    return _success_response(200, {"message": "Account type updated successfully."})

def deactivate_account(conn, body, event):
    """
    Deactivates an account.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
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
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage accounts")
        
        cur.execute("""
            UPDATE account_holders SET is_active = false, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s RETURNING id
        """, (account_holder_id,))

        if not cur.fetchone():
            return _error_response(404, "Account not found or already deactivated.")
        
        cur.execute("""
                    SELECT pi.estate_id FROM account_holders ah 
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.id = %s
                    """, (account_holder_id,))
        
        result = cur.fetchone()

        log(conn, "ACCOUNT_DEACTIVATION", "Account deactivated", user_id, account_holder_id, result[0])

        conn.commit()

    return _success_response(200, {"message": "Account deactivated successfully."})

def activate_account(conn, body, event):
    """
    Activates an account.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")


    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
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
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM account_holders ah
                        JOIN personal_info pi ON ah.personal_info_id = pi.id
                        WHERE ah.user_id = %s AND ah.id = %s
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
            
            if not cur.fetchone():
                return _error_response(403, "You do not have privileges to manage accounts")
        
        cur.execute("""
            UPDATE account_holders SET is_active = true
            WHERE id = %s RETURNING id
        """, (account_holder_id,))

        if not cur.fetchone():
            return _error_response(404, "Account not found.")
        
        cur.execute("""
                    SELECT pi.estate_id FROM account_holders ah 
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.id = %s
                    """, (account_holder_id,))
        
        result = cur.fetchone()

        log(conn, "ACCOUNT_ACTIVATION", "Account activated", user_id, account_holder_id, result[0])

        conn.commit()

    return _success_response(200, {"message": "Account activated successfully."})

def delete_account(conn, body, event):
    """
    Deletes an account and its related personal info.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
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
                            SELECT pi.estate_id 
                            FROM account_holders ah
                            JOIN personal_info pi ON ah.personal_info_id = pi.id
                            WHERE ah.id = %s
                    ) AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                    ) AS exists_flag
                    """, (user_id, account_holder_id))
        
        has_privileges = cur.fetchone()[0]
        if not (has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to manage accounts")
        
        # Delete the personal info associated with this account
        cur.execute("""
            DELETE FROM personal_info
            USING account_holders
            WHERE personal_info.id = account_holders.personal_info_id
            AND account_holders.id = %s
            RETURNING personal_info.estate_id
        """, (account_holder_id,))

        result = cur.fetchone()
        
        if not result:
            return _error_response(404, "Personal info not found.")

        log(conn, "ACCOUNT_DELETION", "Account deleted", user_id, account_holder_id, result[0])

        conn.commit()

    return _success_response(200, {"message": "Account and related personal info deleted successfully."})
