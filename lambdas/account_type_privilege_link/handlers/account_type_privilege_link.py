import json
from psycopg2.extras import RealDictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, log
from middleware import verify_token, cors_wrap

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

def create_privilege_link(conn, body, event):
    """
    Assigns a privilege to an account type after verifying that both exist.
    """
    payload, error = verify_token(event, conn)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can assign privileges.")

    account_type_id = body.get("account_type_id")
    privilege_id = body.get("privilege_id")

    if not account_type_id or not privilege_id:
        return _error_response(400, "Missing 'account_type_id' or 'privilege_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Verify account_type_id exists
        cur.execute("SELECT id FROM account_types WHERE id = %s", (account_type_id,))
        if not cur.fetchone():
            return _error_response(404, "Account type not found.")

        # Verify privilege_id exists
        cur.execute("SELECT id FROM privileges WHERE id = %s", (privilege_id,))
        if not cur.fetchone():
            return _error_response(404, "Privilege not found.")

        # Insert only if both exist
        cur.execute("""
            INSERT INTO account_type_privilege_links (account_type_id, privilege_id)
            VALUES (%s, %s)
            ON CONFLICT (account_type_id, privilege_id) DO NOTHING
            RETURNING account_type_id, privilege_id
        """, (account_type_id, privilege_id))

        if not cur.fetchone():
            return _error_response(409, "Privilege already assigned to this account type.")
        
        log(conn, "ACCOUNT_TYPE_PRIVILEGE_LINK_CREATION", f"Link between privilege '{privilege_id}' and account type '{account_type_id}' created", user_id, None, None)

        conn.commit()

    return _success_response(201, {"message": "Privilege assigned successfully."})



def remove_privilege_link(conn, body, event):
    """
    Removes a privilege from an account type.
    """
    payload, error = verify_token(event, conn)
    if error:
        return error

    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can remove privileges.")

    account_type_id = body.get("account_type_id")
    privilege_id = body.get("privilege_id")

    if not account_type_id or not privilege_id:
        return _error_response(400, "Missing 'account_type_id' or 'privilege_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            DELETE FROM account_type_privilege_links
            WHERE account_type_id = %s AND privilege_id = %s
            RETURNING account_type_id, privilege_id
        """, (account_type_id, privilege_id))
        if not cur.fetchone():
            return _error_response(404, "Privilege link not found.")
        
        log(conn, "ACCOUNT_TYPE_PRIVILEGE_LINK_REMOVAL", f"Link between privilege '{privilege_id}' and account type '{account_type_id}' removed", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Privilege removed successfully."})


def list_account_type_privileges(conn, event):
    """
    Lists privileges assigned to a specific account type with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event, conn)
    if error:
        return error

    if not payload.get("is_admin"):
        return _error_response(403, "Access denied. Only admins can view privileges.")

    path_params = event.get("pathParameters", {})
    account_type_id = path_params.get("account_type_id")

    if not account_type_id:
        return _error_response(400, "Missing 'account_type_id'.")

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
        cur.execute("""
            SELECT COUNT(*) FROM account_type_privilege_links
            WHERE account_type_id = %s
        """, (account_type_id,))
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT atpl.privilege_id AS id, pr.name AS name
            FROM account_type_privilege_links atpl
            JOIN privileges pr ON atpl.privilege_id = pr.id
            WHERE atpl.account_type_id = %s
            ORDER BY pr.name
            LIMIT %s OFFSET %s
        """, (account_type_id, page_size, offset))
        privileges = cur.fetchall()

    return _success_response(200, {
        "privileges": process_db_results(privileges),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })

