import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges_for_estate, get_user_privileges_for_personal_info, get_user_privileges_for_account_holder,send_email_gmail
import random
from datetime import datetime, timedelta
from middleware import verify_token
# import firebase_functions as functions
# import requests
# import uuid

def signup(conn, body):
    """
    Handles account creation for an existing user in a new estate.
    """
    user_id = body.get("user_id")
    estate_id = body.get("estate_id")
    house_address = body.get("house_address")

    # Validate basic required fields.
    if not user_id or not estate_id or not house_address:
        return _error_response(400, "Missing required fields: 'user_id', 'estate_id', or 'house_address'.")

    # Validate personal_info-specific required fields.
    required_fields = ["name", "id_type", "id_num", "contact"]
    missing = [f for f in required_fields if not body.get(f)]
    if missing:
        return _error_response(400, f"Missing required fields: {', '.join(missing)}.")

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

            # Lookup default account type
            cur.execute("SELECT id FROM account_types WHERE name = 'USER_A'")
            row = cur.fetchone()
            if not row:
                return _error_response(500, "Default account type 'USER_A' not found.")
            account_type_id = row["id"]

            # Lookup default access group
            cur.execute("SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'", (estate_id,))
            row = cur.fetchone()
            if not row:
                return _error_response(500, "Default access group 'REGULAR' not found.")
            access_group_id = row["id"]

            # Insert into personal_info
            cur.execute("""
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                estate_id,
                body.get("name"),
                body.get("id_type"),
                body.get("id_num"),
                body.get("contact"),
                account_type_id,
                access_group_id
            ))

            personal_info = cur.fetchone()
            if not personal_info:
                return _error_response(500, "Failed to create personal info.")
            personal_info_id = personal_info["id"]

            # Insert into account_holders
            cur.execute("""
                INSERT INTO account_holders (user_id, personal_info_id, house_address)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (user_id, personal_info_id, house_address))
            account_holder = cur.fetchone()
            if not account_holder:
                return _error_response(500, "Failed to create account holder.")
            account_holder_id = account_holder["id"]

            # Log creation
            log(conn, "REGULAR_ACCOUNT_CREATION", "Resident account created", user_id, account_holder_id, estate_id)

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

# def create_sub_account(conn, body, event):
#     """
#     Creates a **sub-account** for an existing *account holder* (the parent).

#     Behaviour:
#     • The caller must be either the parent account holder themself **or** have
#       MANAGE_ACCOUNTS / MANAGE_ALL privileges in the parent estate (admins are
#       always allowed).
#     • The new sub-account is created in the *same* estate and inherits the
#       parent account holder's house_address (flat / unit number etc.).
#     • A record is inserted into the optional `sub_accounts` link table if it
#       exists.  If that table is not present the function will silently ignore
#       the insert – this keeps the handler forward-compatible with DB
#       migrations.

#     Expected `body` keys
#     --------------------
#     parent_account_holder_id : int   – id of the existing account holder
#     user_id                 : int   – *user* the sub-account belongs to
#     name / id_type / id_num / contact : same fields required by signup()
#     account_type_id         : int   – optional, falls back to USER_B
#     access_group_id         : int   – optional, falls back to REGULAR
#     """

#     # ------------------------------------------------------------------
#     # 1.  Validate input
#     # ------------------------------------------------------------------
#     parent_account_holder_id = body.get("parent_account_holder_id")
#     # child_user_id            = body.get("user_id")
#     child_email            = body.get("email")

#     if not parent_account_holder_id:
#         return _error_response(400, "Missing 'parent_account_holder_id'.")
#     # Auto-generate a brief user_id (initials + 4-digit random) if not provided
#     # if not child_user_id:
#     initials = ''.join(w[0].lower() for w in body.get("name", "").split())[:3] or 'u'
#     child_user_id = f"{initials}{random.randint(1000, 9999)}"
#     otp = str(random.randint(100000, 999999))
#     # Personal-info fields are required (same rule as signup)
#     required_fields = ["name", "id_type", "id_num", "contact"]
#     missing = [f for f in required_fields if not body.get(f)]
#     if missing:
#         return _error_response(400, f"Missing required fields: {', '.join(missing)}.")

#     # Token verification (so we know *who* is making the request)
#     payload, error = verify_token(event)
#     if error:
#         return error

#     caller_user_id = payload.get("user_id")
#     is_admin       = payload.get("is_admin", False)

#     try:
#         with conn.cursor(cursor_factory=RealDictCursor) as cur:
#             # ------------------------------------------------------------------
#             # 2.  Fetch parent account information & privileges check
#             # ------------------------------------------------------------------
#             cur.execute("""
#                 SELECT ah.id               AS account_holder_id,
#                        ah.user_id         AS parent_user_id,
#                        ah.house_address,
#                        pi.estate_id
#                 FROM   account_holders ah
#                 JOIN   personal_info  pi ON pi.id = ah.personal_info_id
#                 WHERE  ah.id = %s
#             """, (parent_account_holder_id,))

#             parent = cur.fetchone()
#             if not parent:
#                 return _error_response(404, "Parent account holder not found.")

#             estate_id    = parent["estate_id"]
#             house_address = parent["house_address"]
#             parent_user_id = parent["parent_user_id"]

#             # Privilege check – caller must be owner, estate manager or admin
#             is_owner = (caller_user_id == parent_user_id)
#             has_priv  = False
#             if not (is_owner or is_admin):
#                 privs = get_user_privileges_for_estate(cur, caller_user_id, estate_id, is_admin=False)
#                 has_priv = privs and privs.can_manage_accounts()
#             if not (is_owner or has_priv or is_admin):
#                 return _error_response(403, "You do not have privileges to create sub-accounts for this parent.")
            
               
#             # ------------------------------------------------------------------
#             # 3.  Prepare defaults – account type & access group (same logic as signup)
#             # ------------------------------------------------------------------
#             # account_type_id  = body.get("account_type_id")
#             # access_group_id  = body.get("access_group_id")

#             # if not account_type_id:
#             cur.execute("SELECT id FROM account_types WHERE name = 'SUB_USER'")
#             row = cur.fetchone()
#             if not row:
#                 return _error_response(500, "Default account type 'SUB_USER' not found.")
#             account_type_id = row["id"]

#             # if not access_group_id:
#             cur.execute("SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'", (estate_id,))
#             row = cur.fetchone()
#             if not row:
#                 return _error_response(500, "Default access group 'REGULAR' not found.")
#             access_group_id = row["id"]

#             # Prevent duplicate child for same user in this estate
#             cur.execute("""
#                 SELECT 1
#                 FROM   account_holders ah
#                 JOIN   personal_info pi ON pi.id = ah.personal_info_id
#                 WHERE  ah.user_id = %s
#                 AND    pi.estate_id = %s
#             """, (child_user_id, estate_id))
#             if cur.fetchone():
#                 return _error_response(409, "User already has an account in this estate.")
#             #Assign priviledges to user later(call the function)
            
#             cur.execute("""
#                 INSERT INTO pending_sub_user(email,otp,otp_expiry,estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
#                 VALUES (%s,%s, NOW() + INTERVAL '10 minutes',%s,%s,%s,%s,%s,%s,%s)
#                 RETURNING id
#             """, (
#                 child_email,
#                 otp,
#                 estate_id,
#                 body.get("name"),
#                 body.get("id_type"),
#                 body.get("id_num"),
#                 body.get("contact"),
#                 account_type_id,
#                 access_group_id
#             ))
#             subject = 'ACCESS ACCOUNT'
#             message = (
#                 "You have been added as a member of house in house_address .\n"
#                 f"{otp}.\n\n"
#                 "Note that you need to download the app through "" on playstore and "" on appstore."
#             )
#             send_email_gmail(child_email, subject, message)
            
#             # ------------------------------------------------------------------
#             # 4.  Insert personal_info & account_holder for the child
#             # ------------------------------------------------------------------
#             # cur.execute("""
#             #     INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
#             #     VALUES (%s, %s, %s, %s, %s, %s, %s)
#             #     RETURNING id
#             # """, (
#             #     estate_id,
#             #     body.get("name"),
#             #     body.get("id_type"),
#             #     body.get("id_num"),
#             #     body.get("contact"),
#             #     account_type_id,
#             #     access_group_id
#             # ))
#             # personal_info_id = cur.fetchone()["id"]

#             # cur.execute("""
#             #     INSERT INTO account_holders (user_id, personal_info_id, house_address)
#             #     VALUES (%s, %s, %s)
#             #     RETURNING id
#             # """, (child_user_id, personal_info_id, house_address))
#             # sub_account_holder_id = cur.fetchone()["id"]

#             # # ------------------------------------------------------------------
#             # # 5.  Store link in sub_accounts table if present
#             # # ------------------------------------------------------------------
#             # try:
#             #     cur.execute("""
#             #         INSERT INTO sub_accounts (parent_account_holder_id, sub_account_holder_id)
#             #         VALUES (%s, %s)
#             #     """, (parent_account_holder_id, sub_account_holder_id))
#             # except psycopg2.errors.UndefinedTable:
#             #     # Table not yet migrated – ignore
#             #     conn.rollback()  # clear error state
#             #     pass

#             # ------------------------------------------------------------------
#             # 6.  Logging & commit
#             # ------------------------------------------------------------------
#             log(conn, "SUB_ACCOUNT_CREATION", f"Sub-account created for parent {parent_account_holder_id}", caller_user_id, sub_account_holder_id, estate_id)
#             conn.commit()

#         return _success_response(201, {
#             "message": "Sub-account created successfully.",
#              "email" : child_email
#             # "sub_account": {
#             #     "parent_account_holder_id": parent_account_holder_id,
#             #     "sub_account_holder_id": sub_account_holder_id,
#             #     "personal_info_id": personal_info_id,
#             #     "user_id": child_user_id,
#             #     "estate_id": estate_id,
#             #     "house_address": house_address
#             # }
#         })

#     except Exception as e:
#         conn.rollback()
#         return _error_response(500, f"An error occurred: {e}")

# def verify_otp(conn, body):
#     token = body.get("token")
#     input_otp = body.get("otp")

#     if not token or not input_otp:
#         return _error_response(400, "Missing token or OTP.")

#     email = decode_token(token)
#     if not email:
#         return _error_response(400, "Invalid token.")

#     with conn.cursor(cursor_factory=RealDictCursor) as cur:
#         cur.execute("""
#             SELECT * FROM pending_sub_user WHERE email = %s
#         """, (email,))
#         row = cur.fetchone()

#         if not row:
#             return _error_response(404, "No pending registration found for this email.")
#         if row["otp"] != input_otp:
#             return _error_response(401, "Invalid OTP.")
#         if row["otp_expiry"] < datetime.utcnow():
#             return _error_response(401, "OTP expired.")
        
#          # ------------------------------------------------------------------
#             # 4.  Insert personal_info & account_holder for the child
#             # ------------------------------------------------------------------
#         cur.execute("""
#             INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
#             VALUES (%s, %s, %s, %s, %s, %s, %s)
#             RETURNING id
#         """, (
#             row["estate_id"],
#             row["name"],
#             row["id_type"],
#             row["id_num"],
#             row["contact"],
#            row["account_type_id"],
#            row["access_group_id"]
#         ))
#         personal_info_id = cur.fetchone()["id"]
#         # Clean up
#         cur.execute("DELETE FROM pending_users WHERE email = %s", (email,))
#         log(conn, "USER_REGISTRATION", f"User '{user_id}' [{email}] registered", user_id, None, None)

#         conn.commit()

#     return _success_response(201, {"message": "Account verified and created successfully.", "user_id": user_id})


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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # cur.execute("""
        #                 SELECT estate_id FROM personal_info
        #                 JOIN account_holders ah ON ah.personal_info
        #                 WHERE personal_info.id = %s
        #             """, (user_id, personal_info_id))
        # result = cur.fetchone()
        # Check if account type exists
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_personal_info(cur, user_id, personal_info_id, is_admin)

        if not privileges:
            return _error_response(403, "Personal info not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
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

        log(conn, "ACCOUNT_TYPE_CHANGE", "Account type changed", user_id, result["id"], result["estate_id"])

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
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

        log(conn, "ACCOUNT_DEACTIVATION", "Account deactivated", user_id, account_holder_id, result["estate_id"])

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin=False)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
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

        log(conn, "ACCOUNT_ACTIVATION", "Account activated", user_id, account_holder_id, result["estate_id"])

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

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
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

        log(conn, "ACCOUNT_DELETION", f"Account deleted {account_holder_id}", user_id, None, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Account and related personal info deleted successfully."})

def get_estate_accounts(conn, event):
    """
    Retrieves all account holders (and their personal info) for a given estate.
    Only admins or users with MANAGE_ALL or MANAGE_ACCOUNTS privileges in that estate can access this data.
    Supports pagination with optional query params: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    # Path param
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")
    if not estate_id:
        return _error_response(400, "Missing 'estate_id' in path parameters.")

    # Pagination
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
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_accounts():
            return _error_response(403, "You do not have privileges to view accounts in this estate.")

        # Count total
        cur.execute("SELECT COUNT(*) FROM account_holders ah JOIN personal_info pi ON ah.personal_info_id = pi.id WHERE pi.estate_id = %s", (estate_id,))
        total = cur.fetchone()["count"]

        # Fetch paginated results
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
            LIMIT %s OFFSET %s
        """, (estate_id, page_size, offset))

        accounts = cur.fetchall()

    return _success_response(200, {
        "accounts": process_db_results(accounts),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


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

        # If not owner, check privileges using enhanced helper
        has_privileges = False
        if not is_owner and not is_admin:
            privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin=False)
            has_privileges = privileges and privileges.can_manage_accounts()

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
