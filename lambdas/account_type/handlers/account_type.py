from database import delete_row, insert_row, update_row
import json
from database import DictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results, log
from middleware import verify_token, cors_wrap

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

def create_account_type(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")

    if not is_admin:
        return _error_response(403, "Access denied. Only admins can create account types.")

    name = body.get("name")

    if not name:
        return _error_response(400, "Missing 'name'.")

    with conn.cursor(cursor=DictCursor) as cur:
        _write_result = insert_row(cur, """
            INSERT INTO account_types (name)
            VALUES (%s)
        """, (name,), table='account_types', columns='id')

        account_type_id = _write_result["id"]

        log(conn, "ACCOUNT_TYPE_CREATED", f"Account type '{name}' created", user_id, None, None)

        conn.commit()

    return _success_response(201, {"message": "Account Type created successfully.", "account_type_id": account_type_id})


def update_account_type(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")
    
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can update account types.")

    account_type_id = body.get("id")
    name = body.get("name")

    if not account_type_id or not name:
        return _error_response(400, "Missing 'id' or 'name'.")

    with conn.cursor(cursor=DictCursor) as cur:
        _write_result = update_row(cur, """
            UPDATE account_types
            SET name = %s, date_updated = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (name, account_type_id), table='account_types', columns='id', where='id = %s', where_count=1)
        if not _write_result:
            return _error_response(404, "Account Type not found.")
        
        log(conn, "ACCOUNT_TYPE_UPDATED", f"Account type '{name}' updated", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Account Type updated successfully.", "account_type_id": account_type_id})


def delete_account_type(conn, body, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    is_admin = payload.get("is_admin", False)
    user_id = payload.get("user_id")
    
    if not is_admin:
        return _error_response(403, "Access denied. Only admins can delete account types.")

    account_type_id = body.get("id")
    if not account_type_id:
        return _error_response(400, "Missing 'id'.")

    with conn.cursor(cursor=DictCursor) as cur:
        _write_result = delete_row(cur, """
            DELETE FROM account_types WHERE id = %s
        """, (account_type_id,), table='account_types', columns='name', where='id = %s', where_count=1)

        result = _write_result
        if not result:
            return _error_response(404, "Account Type not found.")

        log(conn, "ACCOUNT_TYPE_DELETED", f"Account type '{result['name']}' created", user_id, None, None)

        conn.commit()

    return _success_response(200, {"message": "Account Type deleted successfully."})


def get_account_types(conn, event):
    """
    Retrieves all account types with optional pagination.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event, conn)
    if error:
        return error

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
        cur.execute("SELECT COUNT(*) AS count FROM account_types")
        total = cur.fetchone()["count"]

        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM account_types
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))

        account_types = cur.fetchall()

    return _success_response(200, {
        "account_types": process_db_results(account_types),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def get_account_type_by_id(conn, event):
    payload, error = verify_token(event, conn)
    if error:
        return error

    account_type_id = event.get("pathParameters", {}).get("id")
    if not account_type_id:
        return _error_response(400, "Missing account type ID.")

    with conn.cursor(cursor=DictCursor) as cur:
        cur.execute("""
            SELECT id, name, date_created, date_updated
            FROM account_types WHERE id = %s
        """, (account_type_id,))
        account_type = cur.fetchone()
        if not account_type:
            return _error_response(404, "Account Type not found.")

    return _success_response(200, {"account_type": process_db_results([account_type])})
