import json
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token
from psycopg2.extras import RealDictCursor

def change_user_type(conn, body, event):
    """
    Changes user type. Requires admin authentication.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)

    user_id = body.get("user_id")

    body_is_admin = body.get("is_admin", False)

    if not is_admin:
        return _error_response(403, "Access denied. Only admins change user type")

    if not user_id:
        return _error_response(400, "No user id in request body.")

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET is_admin = %s
            WHERE id = %s RETURNING id
        """, (body_is_admin, user_id))
        if not cur.fetchone():
            return _error_response(404, "User not found.")
        
        log(conn, "USER_TYPE_CHANGE", f"User '{user_id}' type changed", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "User type changed successfully."})


def deactivate_user(conn, body, event):
    """
    Deactivates a user account. Requires authentication.
    Prints all internal values for debugging.
    """
    print("\n---[DEBUG] Starting deactivate_user ---")

    # Step 1: Verify Token
    payload, error = verify_token(event)
    if error:
        print("[DEBUG] Token verification failed:", error)
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    # Step 2: Get user_id from body if admin
    body_user_id = body.get("user_id")
    target_user_id = body_user_id if is_admin else user_id

    print("[DEBUG] user_id (from token):", user_id)
    print("[DEBUG] is_admin:", is_admin)
    print("[DEBUG] body_user_id:", body_user_id)
    print("[DEBUG] target_user_id (to deactivate):", target_user_id)

    if is_admin and not body_user_id:
        print("[DEBUG] Admin request missing 'user_id' in body")
        return _error_response(400, "'user_id' field missing.")

    # Step 3: Try DB update
    try:
        with conn.cursor() as cur:
            print("[DEBUG] Executing update query...")
            cur.execute("""
                UPDATE users SET is_active = false, date_updated = CURRENT_TIMESTAMP
                WHERE id = %s RETURNING id, is_active
            """, (target_user_id,))

            result = cur.fetchone()
            print("[DEBUG] Update result:", result)

            if not result:
                print("[DEBUG] No user updated — may not exist or already deactivated.")
                return _error_response(404, "User not found or already deactivated.")
            
            print("[DEBUG] Deactivating associated account_holders...")
            cur.execute("""
                UPDATE account_holders
                SET is_active = false, date_updated = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (target_user_id,))
            print("[DEBUG] Associated account_holders deactivated.")

            print("[DEBUG] Logging deactivation...")
            log(conn, "USER_DEACTIVATED", f"User '{target_user_id}' deactivated", user_id, None, None)

        conn.commit()
        print("[DEBUG] Deactivation committed successfully.")

    except Exception as e:
        conn.rollback()
        print("[ERROR] Exception occurred:", str(e))
        return _error_response(500, f"Internal server error: {str(e)}")

    print("[DEBUG] Returning success response.\n")
    return _success_response(200, {"message": "User deactivated successfully."})


def activate_user(conn, body, event):
    """
    Activates a user account. Requires authentication.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)

    user_id = body.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins activate users")

    if not user_id:
        return _error_response(400, "No user id in request body.")

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET is_active = true, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s RETURNING id
        """, (user_id,))
        if not cur.fetchone():
            return _error_response(404, "User not found or already active.")
        
        log(conn, "USER_ACTIVATED", f"User '{user_id}' activated", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "User reactivated successfully."})

def get_users(conn, event):
    """
    Returns a list of all users. Only admins can access this endpoint.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve user data.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, email, is_active, is_admin, date_created, date_updated FROM users")
        users = process_db_results(cur.fetchall())

    return _success_response(200, {"users": users})

def get_own_accounts(conn, event):
    """
    Retrieves the authenticated user's account details.
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT ah.id AS account_holder_id, pi.id AS personal_info_id, ah.user_id, pi.estate_id, pi.name, pi.expiry, pi.contact, es.name AS estate_name, at.name AS account_type_name, ag.name AS access_group_name,
                   ah.house_address, pi.account_type_id, ah.is_active
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            WHERE ah.user_id = %s
        """, (user_id,))
        accounts = cur.fetchall()

    return _success_response(200, {"accounts": process_db_results(accounts)})

def get_user_accounts(conn, event):
    """
    Retrieves account details for a specific account holder (admin only).
    """
    payload, error = verify_token(event)
    if error:
        return error

    if not payload.get("is_admin"):
        return _error_response(403, "Access denied. Only admins can retrieve account details.")

    user_id = event.get("pathParameters", {}).get("user_id")
    if not user_id:
        return _error_response(400, "Missing account holder ID.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT ah.id AS account_holder_id, pi.name, pi.expiry, pi.contact, es.name AS estate_name, at.name AS account_type_name, pi.id AS personal_info_id, ah.user_id, pi.estate_id,
                   ah.house_address, pi.account_type_id, ah.is_active
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            JOIN account_types at ON pi.account_type_id = at.id
            WHERE ah.user_id = %s
        """, (user_id,))
        accounts = cur.fetchall()

    return _success_response(200, {"accounts": process_db_results(accounts)})