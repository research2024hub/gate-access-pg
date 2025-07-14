import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
import random
from datetime import datetime, timedelta
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

# def signup_resident_by_admin(conn, body, event):
#     """
#     Handles account creation for an existing user in a new estate.
#     """
    
#     payload, error = verify_token(event)
#     if error:
#         return error
    
#     manager_user_id = payload.get("user_id")
    
#     user_id = body.get("user_id")
#     estate_id = body.get("estate_id")
#     house_address = body.get("house_address")

#     # Validate required fields.
#     if not user_id or not estate_id or not house_address:
#         return _error_response(400, "Missing required fields: 'user_id', 'estate_id', or 'house_address'.")

#     try:
#         with conn.cursor(cursor_factory=RealDictCursor) as cur:
            
#             cur.execute("""
#                     SELECT EXISTS (
#                         SELECT 1 FROM account_holders ah
#                         JOIN personal_info pi ON ah.personal_info_id = pi.id
#                         JOIN account_types act ON pi.account_type_id = act.id
#                         JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
#                         JOIN privileges pv ON atpl.privilege_id = pv.id
#                         WHERE ah.user_id = %s AND pi.estate_id = %s
#                         AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
#                     ) AS exists_flag
#                     """, (manager_user_id, estate_id))

#             if not cur.fetchone()["exists_flag"]:
#                 return _error_response(403, "You do not have privileges to manage accounts")
 
#             # Prevent duplicate signup in the same estate.
#             cur.execute("""
#                 SELECT id FROM account_holders
#                 WHERE user_id = %s AND personal_info_id IN (
#                     SELECT id FROM personal_info WHERE estate_id = %s
#                 )
#             """, (user_id, estate_id))
#             if cur.fetchone():
#                 return _error_response(409, "User already has an account in this estate.")

#             # Insert into personal_info.
#             cur.execute("""
#                 INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
#                 VALUES (%s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name='USER_A'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
#                 RETURNING id
#             """, (
#                 estate_id,
#                 body.get("name"),
#                 body.get("id_type"),
#                 body.get("id_num"),
#                 body.get("contact"),
#                 estate_id
#             ))

#             personal_info_row = cur.fetchone()
#             if not personal_info_row:
#                 return _error_response(500, "Failed to create personal info.")
#             personal_info_id = personal_info_row["id"]

#             # Create account holder entry.
#             cur.execute("""
#                 INSERT INTO account_holders (user_id, personal_info_id, house_address)
#                 VALUES (%s, %s, %s)
#                 RETURNING id
#             """, (user_id, personal_info_id, house_address))
#             account_holder_row = cur.fetchone()
#             if not account_holder_row:
#                 return _error_response(500, "Failed to create account holder.")
#             account_holder_id = account_holder_row["id"]

#             log(conn, "REGULAR_ACCOUNT_CREATION", "Resident account created", user_id, account_holder_id, estate_id,)

#             conn.commit()

#         return _success_response(201, {
#             "message": "Signup successful.",
#             "account": {
#                 "account_holder_id": account_holder_id,
#                 "personal_info_id": personal_info_id,
#                 "user_id": user_id,
#                 "estate_id": estate_id,
#                 "house_address": house_address
#             }
#         })
    
#     except Exception as e:
#         conn.rollback()
#         return _error_response(500, f"An error occurred: {e}")

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

# def activate_account_by_user(conn, body, event):
#     """
#     Activates an account.
#     """
#     payload, error = verify_token(event)
#     if error:
#         return error
    
#     user_id = payload.get("user_id")

#     account_holder_id = body.get("account_holder_id")
#     if not account_holder_id:
#         return _error_response(400, "Missing 'account_holder_id'.")

#     with conn.cursor() as cur:
#         cur.execute("""
#                     SELECT EXISTS (
#                         SELECT 1 FROM account_holders ah
#                         WHERE ah.user_id = %s AND ah.id = %s
#                     ) AS is_owner
#                     """, (user_id, account_holder_id))
        
#         is_owner = cur.fetchone()[0]
#         if not (is_owner):
#             return _error_response(403, "You cannot activate this account")
        
#         cur.execute("""
#             UPDATE account_holders SET is_active = true
#             WHERE id = %s RETURNING id
#         """, (account_holder_id,))

#         if not cur.fetchone():
#             return _error_response(404, "Account not found.")
        
#         cur.execute("""
#                     SELECT pi.estate_id FROM account_holders ah 
#                     JOIN personal_info pi ON pi.id = ah.personal_info_id
#                     WHERE ah.id = %s
#                     """, (account_holder_id,))
        
#         result = cur.fetchone()

#         log(conn, "ACCOUNT_ACTIVATION", "Account activated", user_id, account_holder_id, result[0])

#         conn.commit()

#     return _success_response(200, {"message": "Account activated successfully."})

def activate_account(conn, body, event):
    """
    Activates an account.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor() as cur:
        # Privilege check
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s
                  AND pi.estate_id = (
                      SELECT pi2.estate_id
                      FROM account_holders ah2
                      JOIN personal_info pi2 ON pi2.id = ah2.personal_info_id
                      WHERE ah2.id = %s
                  )
                  AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
            ) AS exists_flag
        """, (user_id, account_holder_id))

        if not cur.fetchone()["exists_flag"]:
            return _error_response(403, "You do not have privileges to manage accounts")

        # Activate the account
        cur.execute("""
            UPDATE account_holders
            SET is_active = true
            WHERE id = %s
            RETURNING id
        """, (account_holder_id,))
        if not cur.fetchone():
            return _error_response(404, "Account not found.")

        # Get estate for logging
        cur.execute("""
            SELECT pi.estate_id
            FROM account_holders ah
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
        return _error_response(400, "Missing 'account_holder_id'.")

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

        log(conn, "ACCOUNT_DELETION", f"Account deleted {account_holder_id}", user_id, None, result[0])

        conn.commit()

    return _success_response(200, {"message": "Account and related personal info deleted successfully."})

def get_estate_accounts(conn, event):
    """
    Retrieves all account holders (and their personal info) for a given estate.
    Only admins or users with MANAGE_ALL or MANAGE_ACCOUNTS privileges in that estate can access this data.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    # Parse the estate_id from path parameters, e.g. /account/estate/{estate_id}
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")

    if not estate_id:
        return _error_response(400, "Missing 'estate_id' in path parameters.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # If user is not a global admin, check if they have estate-level privileges.
        if not is_admin:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s
                      AND pi.estate_id = %s
                      AND (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                ) AS has_privilege
            """, (user_id, estate_id))

            result = cur.fetchone()
            if not result or not result["has_privilege"]:
                return _error_response(403, "You do not have privileges to view accounts in this estate.")

        # Now fetch all accounts for the given estate.
        cur.execute("""
            SELECT ah.id AS account_holder_id,
                   ah.user_id,
                   ah.house_address,
                   ah.is_active,
                   pi.id AS personal_info_id,
                   pi.name AS full_name,
                   pi.contact,
                   pi.id_type,
                   pi.id_num,
                   pi.expiry,
                   at.name AS account_type_name,
                   ag.name AS access_group_name,
                   pi.estate_id,
                   es.name AS estate_name
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            JOIN estates es ON pi.estate_id = es.id
            WHERE pi.estate_id = %s
            ORDER BY ah.date_created DESC
        """, (estate_id,))

        accounts = cur.fetchall()

    return _success_response(200, {"accounts": process_db_results(accounts)})


def generate_account_otp(conn, body, event):
    """
    Generates a 6-digit OTP for an account holder. Only the holder, estate managers, or admins can generate.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Verify privileges
        cur.execute("""
            SELECT ah.user_id, pi.estate_id
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            WHERE ah.id = %s
        """, (account_holder_id,))
        
        account_info = cur.fetchone()
        if not account_info:
            return _error_response(404, "Account holder not found.")

        estate_id = account_info["estate_id"]
        account_user_id = account_info["user_id"]

        # Check if user is the owner
        is_owner = (user_id == account_user_id)

        # If not owner, check privileges
        has_privileges = False
        if not is_owner and not is_admin:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM account_holders ah
                    JOIN personal_info pi ON ah.personal_info_id = pi.id
                    JOIN account_types act ON pi.account_type_id = act.id
                    JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                    JOIN privileges pv ON atpl.privilege_id = pv.id
                    WHERE ah.user_id = %s AND pi.estate_id = %s AND 
                          (pv.name = 'MANAGE_ALL' OR pv.name = 'MANAGE_ACCOUNTS')
                ) AS has_privileges
            """, (user_id, estate_id))
            has_privileges = cur.fetchone()["has_privileges"]

        if not (is_owner or has_privileges or is_admin):
            return _error_response(403, "You do not have privileges to generate OTP for this account.")

        # 2. Generate OTP
        otp = str(random.randint(100000, 999999))
        otp_generated_at = datetime.utcnow()  # 1 minute expiry

        # 3. Update account holder
        cur.execute("""
            UPDATE account_holders
            SET otp = %s, otp_generated_at = %s
            WHERE id = %s
        """, (otp, otp_generated_at, account_holder_id))

        log(conn, "OTP_GENERATION", f"OTP generated for account_holder {account_holder_id}", user_id, account_holder_id, estate_id)

        conn.commit()

    return _success_response(200, {"message": "OTP generated successfully.", "otp": otp, "expires_in": 60})


def verify_account_otp(conn, body, event):
    """
    Verifies a 6-digit OTP for an account holder.
    """
    payload, error = verify_token(event)
    if error:
        return error

    account_holder_id = body.get("account_holder_id")
    otp_provided = body.get("otp")

    if not account_holder_id or not otp_provided:
        return _error_response(400, "Missing 'account_holder_id' or 'otp'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Get current OTP
        cur.execute("""
            SELECT otp, otp_generated_at FROM account_holders WHERE id = %s
        """, (account_holder_id,))
        
        account_info = cur.fetchone()
        if not account_info:
            return _error_response(404, "Account holder not found.")

        otp_stored = account_info["otp"]
        otp_generated_at = account_info["otp_generated_at"]

        # 2. Validate
        if not otp_stored:
            return _error_response(400, "No OTP generated for this account.")

        # Check if expired
        if (datetime.utcnow() - otp_generated_at).total_seconds() > 60:
            return _error_response(400, "OTP has expired.")

        if otp_provided != otp_stored:
            return _error_response(400, "Invalid OTP.")

        # 3. Clear OTP after successful verification
        cur.execute("""
            UPDATE account_holders
            SET otp = NULL, otp_generated_at = NULL
            WHERE id = %s
        """, (account_holder_id,))

        conn.commit()

    return _success_response(200, {"message": "OTP verified successfully."})
