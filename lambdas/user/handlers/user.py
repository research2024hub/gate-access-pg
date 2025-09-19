import json
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token
from psycopg2.extras import RealDictCursor
from handlers.auth import send_email_gmail,generate_otp
import bcrypt
import jwt
import os
from datetime import datetime, timezone

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key") 

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

def delete_user(conn, body, event):
    """
    Deletes a user account. Requires authentication.
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = body.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete users.")

    if not user_id:
        return _error_response(400, "No user id in request body.")

    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM users 
            WHERE id = %s 
            RETURNING id
        """, (user_id,))
        
        deleted = cur.fetchone()
        if not deleted:
            return _error_response(404, "User not found.")

        log(conn, "USER_DELETED", f"User '{user_id}' deleted", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "User deleted successfully."})


def get_users(conn, event):
    """
    Returns a paginated list of all users. Only admins can access this endpoint.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can retrieve user data.")

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
        cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT id, email, is_active, is_admin, date_created, date_updated
            FROM users
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))
        users = process_db_results(cur.fetchall())

    return _success_response(200, {
        "users": users,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def get_own_accounts(conn, event):
    """
    Retrieves the authenticated user's account details with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    user_id = payload.get("user_id")

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
        cur.execute("SELECT COUNT(*) FROM account_holders WHERE user_id = %s", (user_id,))
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT ah.id AS account_holder_id, pi.id AS personal_info_id, ah.user_id, pi.estate_id, pi.name, pi.expiry, pi.contact,
                   es.name AS estate_name, at.name AS account_type_name, ag.name AS access_group_name,
                   ah.house_address, pi.account_type_id, ah.is_active
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            JOIN account_types at ON pi.account_type_id = at.id
            JOIN access_groups ag ON pi.access_group_id = ag.id
            WHERE ah.user_id = %s
            ORDER BY ah.date_created DESC
            LIMIT %s OFFSET %s
        """, (user_id, page_size, offset))
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

def get_user_accounts(conn, event):
    """
    Retrieves account details for a specific user (admin only) with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error

    if not payload.get("is_admin"):
        return _error_response(403, "Access denied. Only admins can retrieve account details.")

    path_params = event.get("pathParameters", {})
    user_id = path_params.get("user_id")
    if not user_id:
        return _error_response(400, "Missing 'user_id'.")

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
        cur.execute("SELECT COUNT(*) FROM account_holders WHERE user_id = %s", (user_id,))
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT ah.id AS account_holder_id, pi.name, pi.expiry, pi.contact, es.name AS estate_name,
                   at.name AS account_type_name, pi.id AS personal_info_id, ah.user_id, pi.estate_id,
                   ah.house_address, pi.account_type_id, ah.is_active
            FROM account_holders ah
            JOIN personal_info pi ON ah.personal_info_id = pi.id
            JOIN estates es ON pi.estate_id = es.id
            JOIN account_types at ON pi.account_type_id = at.id
            WHERE ah.user_id = %s
            ORDER BY ah.date_created DESC
            LIMIT %s OFFSET %s
        """, (user_id, page_size, offset))
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

def forgot_password(conn, body):
    email = body.get("email")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Look up active user (do not reveal existence to caller)
        cur.execute(
            "SELECT id FROM users WHERE email = %s AND is_active = TRUE LIMIT 1",
            (email,)
        )
        row = cur.fetchone()
        if not row:
            return _error_response(400, "User not found")
        user_id = row["id"]
        # Create JWT (payload must be dict)
        token = jwt.encode({"user_id": user_id}, JWT_SECRET, algorithm="HS256")
        # Generate OTP and expiry
        reset_otp = generate_otp()
        cur.execute(
            """UPDATE users SET reset_otp = %s, reset_expiry = NOW() + INTERVAL '10 minutes' 
            WHERE id = %s""",
            (reset_otp, user_id)
        )
        conn.commit()
    # Build email
    title = 'RESET PASSWORD'
    message = (
        "We received a request to reset your password.\n"
        f"Use the One-Time Password (OTP) below to reset it.\n\n"
        f"Your OTP Code: {reset_otp}\n\n"
        "If you did not request this, you can safely ignore this email."
    )

    send_email_gmail(email, title, message)
    return _success_response(200, {"message": "success.","token": token})

def verify_reset_otp(conn, body, event):
    # Verify token  
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    
    input_otp =str(body.get("reset_otp"))
    if not user_id or not input_otp:
        return _error_response(400, "Missing user_id or OTP.")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT reset_otp, reset_expiry 
            FROM users 
            WHERE id = %s
        """, (user_id,))
        row = cur.fetchone()
        print(row)
        if not row:
            return _error_response(404, "No OTP found for this user.")
        if row["reset_otp"] != input_otp:
            return _error_response(401, "Invalid OTP.")
        if row["reset_expiry"] < datetime.utcnow():
            return _error_response(401, "OTP expired.")
        # Clean up OTP after successful verification
        cur.execute("""
            UPDATE users 
            SET reset_otp = NULL, reset_expiry = NULL
            WHERE id = %s
        """, (user_id,))
        conn.commit()

    return _success_response(200, {"message": "OTP successfully verified."})


def reset_password(conn,body,event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    
    new_password = body["new_password"]
    confirm_password = body["confirm_password"]
    if new_password == confirm_password:
        new_hashed_password = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:  
            cur.execute("""
            UPDATE users SET password = %s
            WHERE id = %s
            """, (new_hashed_password, user_id))

            log(conn, "USER_PASSWORD_CHANGE", f"User '{user_id}' password changed", user_id, None, None)
            conn.commit()

            return _success_response(200, {"message": "Password changed successfully.", "user_id": user_id})
    
    else:
        return _error_response(500, "Failed to reset password.")
