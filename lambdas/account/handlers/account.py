from database import insert_row, update_row
import json
import database
from database import DictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, log, get_user_privileges_for_estate,get_user_privileges_for_personal_info,get_user_privileges_for_account_holder,send_gmail, notify_user, get_user_privileges, soft_delete_account_holder, as_utc, utc_now
import random
from datetime import datetime, timedelta
from middleware import verify_token, cors_wrap
# import firebase_functions as functions
# import requests
# import uuid

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

def _identity_exists(cur, body):
    # Soft deletion keeps personal_info for history, including its unique identity.
    # Never attach a signup to that row: it may belong to another user and carry
    # existing privileges, vehicles, or guest access.
    cur.execute("""
        SELECT id FROM personal_info
        WHERE estate_id = %s AND id_type = %s AND id_num = %s
    """, (body.get("estate_id"), body.get("id_type"), body.get("id_num")))
    return cur.fetchone() is not None


def _signup_conflict():
    return _error_response(
        409,
        "An account or identity already exists in this estate. "
        "If your account was deleted, contact the estate administrator for review. "
        "Signup cannot restore previous access.",
    )


def signup(conn, body, event=None):
    """
    Handles account creation for an existing user in a new estate.
    """
    payload, error = verify_token(event or {}, conn)
    if error:
        return error
    user_id = payload.get("user_id")
    if not user_id:
        return _error_response(403, "A resident login is required.")
    if body.get("user_id") is not None and str(body["user_id"]) != str(user_id):
        return _error_response(403, "You can only sign up for your own account.")
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
        with conn.cursor(cursor=DictCursor) as cur:
            # Prevent duplicate signup in the same estate.
            cur.execute("""
                SELECT id FROM account_holders
                WHERE user_id = %s AND deleted_at IS NULL AND personal_info_id IN (
                    SELECT id FROM personal_info WHERE estate_id = %s
                )
            """, (user_id, estate_id))
            if cur.fetchone():
                return _error_response(409, "User already has an account in this estate.")

            cur.execute("""
                SELECT id FROM personal_info
                WHERE estate_id = %s AND id_type = %s AND id_num = %s
                FOR UPDATE
            """, (estate_id, body["id_type"], body["id_num"]))
            identity = cur.fetchone()
            if identity:
                cur.execute("""
                    SELECT id, user_id, deleted_at, owner_account_holder_id
                    FROM account_holders WHERE personal_info_id = %s FOR UPDATE
                """, (identity["id"],))
                holders = cur.fetchall()
                if (len(holders) != 1 or str(holders[0]["user_id"]) != str(user_id)
                        or holders[0]["deleted_at"] is None
                        or holders[0]["owner_account_holder_id"] is not None):
                    return _signup_conflict()
                account_holder_id = holders[0]["id"]
                _write_result = update_row(cur, """
                    UPDATE account_holders
                    SET deleted_at = NULL, is_active = false, house_address = %s,
                        otp = NULL, otp_generated_at = NULL, date_updated = CURRENT_TIMESTAMP
                    WHERE id = %s AND deleted_at IS NOT NULL
                """, (house_address, account_holder_id), table='account_holders', columns='id', where='id = %s AND deleted_at IS NOT NULL', where_count=1)
                if not _write_result:
                    return _signup_conflict()
                log(conn, "ACCOUNT_REREGISTRATION", "Returning resident awaiting administrator approval",
                    user_id, account_holder_id, estate_id)
                conn.commit()
                return _success_response(200, {
                    "message": "Re-registration submitted. Awaiting estate administrator approval.",
                    "account": {"account_holder_id": account_holder_id,
                                "personal_info_id": identity["id"], "user_id": user_id,
                                "estate_id": estate_id, "house_address": house_address,
                                "is_active": False}
                })

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
            _write_result = insert_row(cur, """
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                estate_id,
                body.get("name"),
                body.get("id_type"),
                body.get("id_num"),
                body.get("contact"),
                account_type_id,
                access_group_id
            ), table='personal_info', columns='id')

            personal_info = _write_result
            if not personal_info:
                return _error_response(500, "Failed to create personal info.")
            personal_info_id = personal_info["id"]

            # Insert into account_holders
            _write_result = insert_row(cur, """
                INSERT INTO account_holders (user_id, personal_info_id, house_address)
                VALUES (%s, %s, %s)
            """, (user_id, personal_info_id, house_address), table='account_holders', columns='id')
            account_holder = _write_result
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

    except database.IntegrityError as exc:
        # A concurrent signup can pass the prechecks; the database is authoritative.
        conn.rollback()
        if exc.args[0] != 1062:
            return _error_response(500, "Unable to create account.")
        return _signup_conflict()
    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred: {e}")


# def signup_resident_by_admin(conn, body, event):
#     """
#     Handles account creation for an existing user in a new estate.
#     """
    
#     payload, error = verify_token(event, conn)
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
#         with conn.cursor(cursor=DictCursor) as cur:
            
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


#             personal_info_row = cur.fetchone()
#             if not personal_info_row:
#                 return _error_response(500, "Failed to create personal info.")
#             personal_info_id = personal_info_row["id"]


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
        with conn.cursor(cursor=DictCursor) as cur:
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
                WHERE user_id = %s AND deleted_at IS NULL AND personal_info_id IN (
                    SELECT id FROM personal_info WHERE estate_id = %s
                )
            """, (user_id, estate_id))
            if cur.fetchone():
                return _error_response(409, "User already has an account in this estate.")

            if _identity_exists(cur, body):
                return _signup_conflict()

            # Insert into personal_info.
            _write_result = insert_row(cur, """
                INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                VALUES (%s, %s, %s, %s, %s, (SELECT id FROM account_types WHERE name='ADMIN'), (SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'))
            """, (
                estate_id,
                body.get("name"),
                body.get("id_type"),
                body.get("id_num"),
                body.get("contact"),
                estate_id
            ), table='personal_info', columns='id')

            personal_info_row = _write_result
            if not personal_info_row:
                return _error_response(500, "Failed to create personal info.")
            personal_info_id = personal_info_row["id"]

            # Create account holder entry.
            _write_result = insert_row(cur, """
                INSERT INTO account_holders (user_id, personal_info_id, house_address, is_active)
                VALUES (%s, %s, %s, true)
            """, (user_id, personal_info_id, house_address), table='account_holders', columns='id')
            account_holder_row = _write_result
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
    
    except database.IntegrityError as exc:
        conn.rollback()
        if exc.args[0] != 1062:
            return _error_response(500, "Unable to create account.")
        return _signup_conflict()
    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred: {e}")

# def create_sub_account(conn, body, event):
#     # ------------------------------------------------------------------
#     # 1.  Validate input
#     # ------------------------------------------------------------------
#     parent_account_holder_id = body.get("parent_account_holder_id")
#     child_email            = body.get("email")

#     if not parent_account_holder_id:
#         return _error_response(400, "Missing 'parent_account_holder_id'.")
#     otp = str(random.randint(100000, 999999))
#     # Personal-info fields are required (same rule as signup)
#     required_fields = ["name", "id_type", "id_num", "contact"]
#     missing = [f for f in required_fields if not body.get(f)]
#     if missing:
#         return _error_response(400, f"Missing required fields: {', '.join(missing)}.")
#     name = body.get("name")
#     id_type = body.get("id_type")
#     id_num = body.get("id_num")
#     contact = body.get("contact")
#     # Token verification (so we know *who* is making the request)
#     payload, error = verify_token(event, conn)
#     if error:
#         return error

#     caller_user_id = payload.get("user_id")
#     is_admin       = payload.get("is_admin", False)

#     try:
#         with conn.cursor(cursor=DictCursor) as cur:
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
#                 privs =get_user_privileges_for_account_holder(cur, parent_user_id, parent_account_holder_id, is_admin = False)
#                 has_priv = privs and privs.can_manage_sub_users()  
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
#                 WHERE  pi.contact = %s
#                 AND    pi.estate_id = %s
#             """, (contact, estate_id))
#             if cur.fetchone():
#                 return _error_response(409, "User already has an account in this estate.")
#             #Assign priviledges to user later(call the function)
            

            
#             subject = 'ACCESS ACCOUNT'
#             message = (
#                 "You have been added as a member of house in house_address.\n"
#                 f"Activate this account using this one time password: {otp}.\n OTP expires in 30 minutes.\n"
#                 "Note that you need to download the app through "" on playstore and "" on appstore and sign-up."
#             )
#             send_email_gmail(child_email, subject, message)

#             # ------------------------------------------------------------------
#             # 6.  Logging & commit
#             # ------------------------------------------------------------------
#             log(conn, "SUB_ACCOUNT_CREATION", f"Sub-account created for parent {parent_account_holder_id}", caller_user_id, parent_account_holder_id, estate_id)
#             conn.commit()

#         return _success_response(201, {
#             "message": "Sub-account created successfully.",
#             "sub_account": {
#                   #"parent_account_holder_id": parent_account_holder_id,
#                   "email" : child_email,
#                   "pending_holder_id": pending_holder_id,
#                   "personal_info_id": personal_info_id
#             #     "user_id": child_user_id,
#             #     "estate_id": estate_id,
#             #     "house_address": house_address
#             }
#         })

#     except Exception as e:
#         conn.rollback()
#         return _error_response(500, f"An error occurred: {e}")

# def verify_otp(conn, body, event):
#     payload, error = verify_token(event, conn)
#     if error:
#         return error
    
#     user_id = payload.get("user_id")
#     input_otp = body.get("otp")
#     personal_info_id =body.get("personal_info_id")
#     name = body.get("name")
#     if not input_otp or not personal_info_id:
#         return _error_response(400, "Missing OTP or personal_info_id.")
   
#     with conn.cursor(cursor=DictCursor) as cur:
#         cur.execute("""
#             SELECT id, otp, otp_generated_at FROM pending_account_holders WHERE personal_info_id = %s
#             """, 
#             (personal_info_id,))
            
#         row = cur.fetchone()

#         if not row:
#             return _error_response(404, "No Otp found for this user.")
#         if row["otp"] != input_otp:
#             return _error_response(401, "Invalid OTP.")
#         if row["otp_generated_at"] < datetime.utcnow():
#             return _error_response(401, "OTP expired.")
#         pending_holder_id = row["id"] 
#         # cur.execute(""""
#         # UPDATE account_holders
#         # SET user_id = %s, is_active = TRUE
#         # WHERE personal_info_id = %s""",(user_id, personal_info_id,))
        
#        # Assuming 'user_id_value' is the Python variable holding the user ID
# # And assuming you want to copy specific columns from pending_account_holders

    
#         log(conn, "SUB_USER_REGISTRATION", f"Household Member '{name}' registered", user_id, None, None)

#         conn.commit()

#     return _success_response(201, {"message": "Account verified and created successfully.", "user_id": user_id})


def change_account_type(conn, body, event):
    """
    Allows an admin to change an account holder's account type.
    """
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id = body.get("personal_info_id")
    account_type_id = body.get("account_type_id")

    if not personal_info_id or not account_type_id:
        return _error_response(400, "Missing 'personal_info_id' or 'account_type_id'.")

    with conn.cursor(cursor=DictCursor) as cur:
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
        _write_result = update_row(cur, """
            UPDATE personal_info
            SET account_type_id = %s, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (account_type_id, personal_info_id), table='personal_info', columns='id', where='id = %s', where_count=1)

        if not _write_result:
            return _error_response(404, "Personal info not found.")

        cur.execute("""
                    SELECT ah.id, pi.estate_id FROM account_holders ah
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.personal_info_id = %s AND ah.deleted_at IS NULL
                    """, (personal_info_id,))

        result = cur.fetchone()

        log(conn, "ACCOUNT_TYPE_CHANGE", "Account type changed", user_id, result["id"], result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Account type updated successfully."})

def deactivate_account(conn, body, event):
    """
    Deactivates an account.
    """
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
            return _error_response(403, "You do not have privileges to manage accounts")

        _write_result = update_row(cur, """
            UPDATE account_holders SET is_active = false, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s AND deleted_at IS NULL
        """, (account_holder_id,), table='account_holders', columns='id', where='id = %s AND deleted_at IS NULL', where_count=1)

        if not _write_result:
            return _error_response(404, "Account not found or already deactivated.")

        cur.execute("""
                    SELECT pi.estate_id FROM account_holders ah
                    JOIN personal_info pi ON pi.id = ah.personal_info_id
                    WHERE ah.id = %s AND ah.deleted_at IS NULL
                    """, (account_holder_id,))

        result = cur.fetchone()

        log(conn, "ACCOUNT_DEACTIVATION", "Account deactivated", user_id, account_holder_id, result["estate_id"])

        conn.commit()

    return _success_response(200, {"message": "Account deactivated successfully."})

# def activate_account_by_user(conn, body, event):
#     """
#     Activates an account.
#     """
#     payload, error = verify_token(event, conn)
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
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")
    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'")

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        # privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin=is_admin)
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin=is_admin)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
            return _error_response(403, "You do not have privileges to manage accounts")

        # Lock the account and identify the resident to notify after approval.
        cur.execute("""
            SELECT ah.user_id
            FROM account_holders ah
            WHERE ah.id = %s AND ah.deleted_at IS NULL FOR UPDATE
        """, (account_holder_id,))
        target = cur.fetchone()
        if not target:
            return _error_response(404, "Account not found or deleted.")

        # Activate the account
        _write_result = update_row(cur, """
            UPDATE account_holders
            SET is_active = true
            WHERE id = %s AND deleted_at IS NULL
        """, (account_holder_id,), table='account_holders', columns='id', where='id = %s AND deleted_at IS NULL', where_count=1)
        if not _write_result:
            return _error_response(404, "Account not found or deleted.")

        # Get estate for logging
        cur.execute("""
            SELECT pi.estate_id
            FROM account_holders ah
            JOIN personal_info pi ON pi.id = ah.personal_info_id
            WHERE ah.id = %s AND ah.deleted_at IS NULL
        """, (account_holder_id,))
        result = cur.fetchone()

        log(conn, "ACCOUNT_ACTIVATION", "Account activated", user_id, account_holder_id, result["estate_id"])

        conn.commit()
        title = "ACCOUNT ACTIVATATED"
        message = f"Welcome Aboard \n Your account is now fully active. We’re glad to have you with us!"
        notify_user(str(target["user_id"]),title,message)

    return _success_response(200, {"message": "Account activated successfully."})


def delete_account(conn, body, event):
    """
    Soft-deletes an account holder (sets deleted_at; the row and its
    personal_info, guests, vehicles and logs are all retained).
    """
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin")

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin)

        if not privileges:
            return _error_response(403, "Account holder not found or you do not have an account in this estate")

        if not privileges.can_manage_accounts():
            return _error_response(403, "You do not have privileges to manage accounts")

        estate_id = privileges.estate_id

        # Soft delete: flag the account holder, keep everything else.
        deleted = soft_delete_account_holder(cur, account_holder_id)
        if not deleted:
            return _error_response(404, "Account not found or already deleted.")

        log(conn, "ACCOUNT_DELETION", f"Account soft-deleted {account_holder_id}", user_id, account_holder_id, estate_id)

        conn.commit()

    return _success_response(200, {"message": "Account deleted successfully."})

def get_estate_accounts(conn, event):
    """
    Retrieves all account holders (and their personal info) for a given estate.
    Only admins or users with MANAGE_ALL or MANAGE_ACCOUNTS privileges in that estate can access this data.
    Supports pagination with optional query params: ?page=1&page_size=20
    """
    payload, error = verify_token(event, conn)
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

    with conn.cursor(cursor=DictCursor) as cur:
        # Check privileges using enhanced helper
        privileges = get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)

        if not privileges:
            return _error_response(403, "You do not have an account in this estate")

        if not privileges.can_manage_accounts():
            return _error_response(403, "You do not have privileges to view accounts in this estate.")

        # Count total
        cur.execute("SELECT COUNT(*) AS count FROM account_holders ah JOIN personal_info pi ON ah.personal_info_id = pi.id WHERE pi.estate_id = %s AND ah.deleted_at IS NULL", (estate_id,))
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
            WHERE pi.estate_id = %s AND ah.deleted_at IS NULL
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
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    account_holder_id = body.get("account_holder_id")
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # 1. Verify privileges
        cur.execute("""
            SELECT ah.user_id, pi.estate_id
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            WHERE ah.id = %s AND ah.deleted_at IS NULL
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
        otp_generated_at = utc_now()  # aware UTC; stored correctly in timestamp or timestamptz

        # 3. Update account holder
        cur.execute("""
            UPDATE account_holders
            SET otp = %s, otp_generated_at = %s
            WHERE id = %s AND deleted_at IS NULL
        """, (otp, otp_generated_at, account_holder_id))

        log(conn, "OTP_GENERATION", f"OTP generated for account_holder {account_holder_id}", user_id, account_holder_id, estate_id)

        conn.commit()

    return _success_response(200, {"message": "OTP generated successfully.", "otp": otp, "expires_in": 60})


def verify_account_otp(conn, body, event):
    """
    Verifies a 6-digit OTP for an account holder.
    """
    payload, error = verify_token(event, conn)
    if error:
        return error
    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "TABLET"):
        return _error_response(401, "Unauthorized. Not a registered tablet")

    # account_holder_id = body.get("account_holder_id")
    otp_provided = body.get("otp")
    # if not account_holder_id or not otp_provided:
    #     return _error_response(400, "Missing 'account_holder_id' or 'otp'.")

    with conn.cursor(cursor=DictCursor) as cur:
        # 1. Get current OTP
        # cur.execute("""
        #     SELECT otp, otp_generated_at FROM account_holders WHERE id = %s
        # """, (account_holder_id,))
        cur.execute(
            """
            SELECT pi.name, ah.id, ah.user_id, pi.estate_id, ah.otp_generated_at, ah.otp
            FROM account_holders ah
            JOIN personal_info pi ON pi.id = ah.personal_info_id
            WHERE ah.otp = %s
            AND ah.deleted_at IS NULL
            AND ah.is_active = TRUE
            AND pi.estate_id = (SELECT estate_id FROM gates WHERE id = %s)
            """,(otp_provided, gate_id,)
        )
        account_info = cur.fetchone()
        if not account_info:
            return _error_response(404, "Invalid OTP or Account not found for this estate.")

        otp_stored = account_info["otp"]
        otp_generated_at = account_info["otp_generated_at"]
        account_holder_id = account_info["id"]

        # 2. Validate
        if not otp_stored:
            return _error_response(400, "No OTP generated for this account.")

        # Check if expired
        if (utc_now() - as_utc(otp_generated_at)).total_seconds() > 60:
            return _error_response(400, "OTP has expired.")

        # if otp_provided != otp_stored:
        #     return _error_response(400, "Invalid OTP.")

        # 3. Clear OTP after successful verification
        cur.execute("""
            UPDATE account_holders
            SET otp = NULL, otp_generated_at = NULL
            WHERE id = %s
        """, (account_holder_id,))

        conn.commit()

    return _success_response(200, {"message": "OTP verified successfully."})

# ===============================================================
#  PERSONAL-INFO  PRIVILEGE LINK  (attach privilege to a person)
# ===============================================================

# def create_personal_info_privilege_link(conn, body, event):
#     # 1.  Authentication / basic validation
#     payload, error = verify_token(event, conn)
#     if error:
#         return error

#     actor_user_id = payload.get("user_id")
#     is_admin = payload.get("is_admin", False)

#     personal_info_id = body.get("personal_info_id")
#     privilege_id = body.get("privilege_ids")

#     if not personal_info_id or not privilege_id:
#         return _error_response(400, "Missing 'personal_info_id' or 'privilege_id'.")

#     with conn.cursor(cursor=DictCursor) as cur:
#         # 2. Ensure personal_info exists (and get estate)
#         cur.execute("SELECT estate_id FROM personal_info WHERE id = %s", (personal_info_id,))
#         row = cur.fetchone()
#         if not row:
#             return _error_response(404, "Personal info not found.")
#         estate_id = row["estate_id"]

#         # 3. Privilege gate (skip if global admin)
#         if not is_admin:
#             priv_ctx = get_user_privileges_for_estate(cur, actor_user_id, estate_id, is_admin=False)
#             if not (priv_ctx and priv_ctx.can_manage_accounts()):
#                 return _error_response(403, "You do not have privileges to link privileges in this estate.")

#         # 4. Verify privilege exists
#         cur.execute("SELECT id FROM privileges WHERE id = %s", (privilege_id,))
#         if not cur.fetchone():
#             return _error_response(404, "Privilege not found.")


#         if not cur.fetchone():
#             return _error_response(409, "Privilege already linked to this personal info.")

#         # 6. Audit log & commit
#         log(
#             conn,
#             "PERSONAL_INFO_PRIVILEGE_LINK",
#             f"Linked privilege '{privilege_id}' to personal_info '{personal_info_id}'",
#             actor_user_id,
#             None,
#             estate_id,
#         )

#         conn.commit()

#     return _success_response(201, {"message": "Privilege linked successfully."})

# def assign_selected_privileges_to_personal_info(conn, body, event):                                                       
#     """                                                                                                                   
#     Grant *multiple* privileges (subset chosen in UI) to one person.                                                      
                                                                                                                        
#     Body:                                                                                                                 
#         personal_info_id : int                                                                                            
#         privilege_ids    : list[int]                                                                                      
#     """                                                                                                                   
#     payload, error = verify_token(event, conn)                                                                                  
#     if error:                                                                                                             
#         return error                                                                                                      
                                                                                                                           
#     actor_id   = payload.get("user_id")                                                                                   
#     is_admin   = payload.get("is_admin", False)                                                                           
#     personal_info_id = body.get("personal_info_id")                                                                       
#     privilege_ids    = body.get("privilege_ids") or []  
#     parent_account_holder_id = body.get("parent_account_holder_id")                                                                  
                                                                                                                           
#     if not personal_info_id or not privilege_ids:                                                                         
#         return _error_response(400, "personal_info_id & privilege_ids required")                                          
                                                                                                                           
#     with conn.cursor(cursor=DictCursor) as cur:
#          # 1.  Resolve estate & security-check -------------                                                               
#         cur.execute("SELECT estate_id FROM personal_info WHERE id=%s",                                                    
#                      (personal_info_id,))                                                                                  
#         row = cur.fetchone()                                                                                              
#         if not row:                                                                                                       
#             return _error_response(404, "Personal info not found")                                                        
                                                                                                                           
#         estate_id = row["estate_id"]                                                                                      
#         if not is_admin:                                                                                                  
#             pc = get_user_privileges_for_account_holder(cur, actor_id, parent_account_holder_id, is_admin=False)                                                 
#         if not (pc and pc.can_manage_sub_users()):                                                                     
#             return _error_response(403, "user cannot manage sub_user")                                                    
                                                                                                                        
                                                                                                                           
                                                                                                                           
#         log(conn,                                                                                                         
#             "PERSONAL_INFO_PRIVILEGE_BULK_LINK",                                                                          
#             f"Assigned privileges {privilege_ids} to personal_info {personal_info_id}",                                   
#             actor_id, None, estate_id)                                                                                    
                                                                                                                        
#         conn.commit()                                                                                                     
                                                                                                                        
#     return _success_response(201, {                                                                                       
#         "message": "Privileges assigned",                                                                                 
#         "personal_info_id": personal_info_id,                                                                             
#         "privilege_ids": privilege_ids                                                                                    
#     })                                                                                                                    
                  
# def send_sub_user_otp(conn, body, event):
#     payload, error = verify_token(event, conn)                                                                                  
#     if error:                                                                                                             
#         return error                                                                                                      
                                                                                                                            
#     pending_holder_id = body.get("pending_holder_id")
#     email = body.get("email")
#     otp = str(random.randint(100000, 999999))
#     with conn.cursor(cursor=DictCursor) as cur:
#         cur.execute("""
#             UPDATE pending_account_holder SET otp= %s, otp_generated_at = NOW() + INTERVAL 30 MINUTE
#             WHERE pending_holder_id = %s
#         """, (otp, pending_holder_id))
#         conn.commit()
#     title = 'Your OTP Code'
#     message =f"Your OTP is: {otp}."
#     send_email_gmail(email, title, message)

#     return _success_response(200, {
#         "message": "A new OTP has been sent to your email.",
        
#     })

def update_account(conn, body, event):    
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    caller_user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False) # Default to False if not present
    
    if not caller_user_id and not is_admin:
        return _error_response(401, "Invalid token or user ID.")

    # 2. INPUT: Get what to update and which account to target
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    access_group_id = body.get("access_group_id")
    account_holder_id_to_edit = body.get("account_holder_id")
    if not account_holder_id_to_edit:
        # Fixed the error message to match the check
        return _error_response(400, "Missing 'account_holder_id' in request body.")
    
    if all(v is None for v in [name, id_type, id_num, contact, access_group_id]):
        return _error_response(400, "No fields provided to update.")
    # 4. EXECUTION: Run the single, atomic, and secure query
    with conn.cursor(cursor=DictCursor) as cur:
        # Lock and authorize the same row before changing it in this transaction.
        cur.execute("""
            SELECT p.id AS personal_info_id,
                   ah_sub.id AS matched_account_holder_id,
                   ah_sub.user_id AS matched_user_id, p.estate_id
            FROM personal_info p
            JOIN account_holders ah_sub ON p.id = ah_sub.personal_info_id
            LEFT JOIN account_holders ah_owner
                ON ah_sub.owner_account_holder_id = ah_owner.id
                AND ah_owner.deleted_at IS NULL
            WHERE ah_sub.id = %s AND ah_sub.deleted_at IS NULL
              AND (ah_sub.user_id = %s OR ah_owner.user_id = %s OR %s = TRUE)
            FOR UPDATE
        """, (account_holder_id_to_edit, caller_user_id, caller_user_id, is_admin))
        result = cur.fetchone()
        if result:
            cur.execute("""
                UPDATE personal_info
                SET name = COALESCE(%s, name), id_type = COALESCE(%s, id_type),
                    id_num = COALESCE(%s, id_num), contact = COALESCE(%s, contact),
                    access_group_id = COALESCE(%s, access_group_id)
                WHERE id = %s
            """, (name, id_type, id_num, contact, access_group_id, result["personal_info_id"]))

        if not result:
            conn.rollback()
            # This is now our *only* permission check. If no rows are
            # returned, the user had no permission or the ID was wrong.
            return _error_response(404, "Account holder not found or you do not have permission to edit this user.")

        # Log the action
        log(conn, "ACCOUNT_UPDATE", f"Account updated {result['matched_account_holder_id']}", caller_user_id, None, result["estate_id"])
        
        conn.commit()

    return _success_response(200, {"message": "Account and related personal info updated successfully."})
