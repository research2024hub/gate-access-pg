import json
from psycopg2.extras import RealDictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, process_db_results
from middleware import verify_token, cors_wrap
from datetime import datetime

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))


def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message)) 

def get_logs_by_estate(conn, event):
    """
    Retrieves logs for a specific estate with pagination.
    Only admins or users with VIEW_LOGS or MANAGE_ALL privileges can access this data.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")
    query_params = event.get("queryStringParameters") or {}
    start_date = query_params.get("start_date")
    end_date = query_params.get("end_date")

    if not estate_id:
        return _error_response(400, "Missing 'estate_id'.")
    if not (start_date and end_date):
        return _error_response(400, "Missing 'start_date' or 'end_date' query parameter.")
    try:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return _error_response(400, "Invalid 'start_date' or 'end_date'. Use ISO-8601 format.")

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
        # Privilege check
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM users u
                JOIN account_holders ah ON u.id = ah.user_id
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE u.id = %s AND pi.estate_id = %s
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'VIEW_LOGS')
            ) AS exists_flag
        """, (user_id, estate_id))

        if not (cur.fetchone()["exists_flag"] or is_admin):
            return _error_response(403, "You do not have privileges to retrieve logs for this estate.")
        
        # Total count
        cur.execute("SELECT COUNT(*) FROM logs WHERE estate_id = %s", (estate_id,))
        total = cur.fetchone()["count"]

        # Paginated log retrieval
        cur.execute("""
            SELECT * FROM logs
            WHERE estate_id = %s 
                AND type != 'GATE_CONTROLLER_HEARTBEAT'
                AND date_created BETWEEN %s AND %s
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (estate_id, start, end, page_size, offset))

        logs = cur.fetchall()

    return _success_response(200, {
        "estate_id": estate_id,
        "logs": process_db_results(logs),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def get_logs_by_account_holder(conn, event):
    """
    Retrieves logs for a specific account holder with pagination.
    Only the account holder (linked via user_id) or an admin can access this data.
    Supports query parameters: ?page=1&page_size=20
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    path_params = event.get("pathParameters", {})
    account_holder_id = path_params.get("account_holder_id")
    query_params = event.get("queryStringParameters") or {}
    start_date = query_params.get("start_date")
    end_date = query_params.get("end_date")
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

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
        # Privilege check
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
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM account_holders 
                    WHERE user_id = %s AND id = %s
                ) AS exists_flag
            """, (user_id, account_holder_id))
            if not cur.fetchone()["exists_flag"]:
                return _error_response(403, "You do not have privileges to view logs for this account holder.")

        # Count total logs for pagination
        cur.execute("""
            SELECT COUNT(*) FROM logs
            WHERE target_account_holder_id = %s OR actor_user_id = (
                SELECT user_id FROM account_holders WHERE id = %s
            )
        """, (account_holder_id, account_holder_id))
        total = cur.fetchone()["count"]

        # Fetch logs with pagination
        cur.execute("""
            SELECT *
            FROM logs
            WHERE (
                target_account_holder_id = %s OR actor_user_id = (
                SELECT user_id FROM account_holders WHERE id = %s
            ) 
            )
            AND date_created BETWEEN %s AND %s
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """, (account_holder_id, account_holder_id, start, end, page_size, offset))
        
        logs = cur.fetchall()

    return _success_response(200, {
        "account_holder_id": account_holder_id,
        "logs": process_db_results(logs),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })


def search_logs_by_estate(conn, event):
    payload, error = verify_token(event)
    if error: return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")
    
    if not estate_id:
        return _error_response(400, "Missing 'estate_id'.")

    # Extract query parameters
    query_params = event.get("queryStringParameters") or {}
    search_plate = query_params.get("plate", "").strip()
    search_name = query_params.get("name", "").strip()
    start_date_str = query_params.get("start_date")
    end_date_str = query_params.get("end_date")
    
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
    except ValueError:
        return _error_response(400, "Invalid pagination parameters.")
    
    offset = (page - 1) * page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Privilege check
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM users u
                JOIN account_holders ah ON u.id = ah.user_id
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN account_types act ON pi.account_type_id = act.id
                JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE u.id = %s AND pi.estate_id = %s
                AND (pv.name = 'MANAGE_ALL' OR pv.name = 'VIEW_LOGS')
            ) AS exists_flag
        """, (user_id, estate_id))
        
        if not (cur.fetchone()["exists_flag"] or is_admin):
            return _error_response(403, "Access denied.")

        # --- DYNAMIC SQL BUILDING ---
        filters = ["estate_id = %s", "type != 'GATE_CONTROLLER_HEARTBEAT'"]
        params = [estate_id]

        # Add Optional Date Range Filter
        if start_date_str and end_date_str:
            try:
                # Handle ISO-8601 formatting (handling Z for UTC)
                start = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                filters.append("date_created BETWEEN %s AND %s")
                params.extend([start, end])
            except ValueError:
                return _error_response(400, "Invalid date format. Use ISO-8601.")

        # Add Search by Plate (inside message)
        if search_plate:
            filters.append("message ILIKE %s")
            params.append(f"%{search_plate}%")

        # Add Search by Name (inside message)
        if search_name:
            filters.append("message ILIKE %s")
            params.append(f"%{search_name}%")

        # Finalize the WHERE clause
        where_clause = " WHERE " + " AND ".join(filters)

        # 1. Total Count for Pagination (with filters)
        cur.execute(f"SELECT COUNT(*) FROM logs {where_clause}", tuple(params))
        total = cur.fetchone()["count"]

        # 2. Paginated Results
        fetch_sql = f"""
            SELECT * FROM logs 
            {where_clause} 
            ORDER BY date_created DESC 
            LIMIT %s OFFSET %s
        """
        cur.execute(fetch_sql, tuple(params + [page_size, offset]))
        logs = cur.fetchall()

    return _success_response(200, {
        "estate_id": estate_id,
        "logs": process_db_results(logs),
        "pagination": {
            "page": page,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })
    
    


def search_logs_by_account_holder(conn, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    path_params = event.get("pathParameters", {})
    account_holder_id = path_params.get("account_holder_id")
    
    if not account_holder_id:
        return _error_response(400, "Missing 'account_holder_id'.")

    # Extract query parameters
    query_params = event.get("queryStringParameters") or {}
    search_plate = query_params.get("plate", "").strip()
    search_name = query_params.get("name", "").strip()
    start_date_str = query_params.get("start_date")
    end_date_str = query_params.get("end_date")
    
    try:
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 20))
    except ValueError:
        return _error_response(400, "Invalid pagination parameters.")

    offset = (page - 1) * page_size

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # --- 1. Privilege Check (Remains the same) ---
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
            cur.execute("SELECT EXISTS (SELECT 1 FROM account_holders WHERE user_id = %s AND id = %s) AS exists_flag", (user_id, account_holder_id))
            if not cur.fetchone()["exists_flag"]:
                return _error_response(403, "Access denied.")

        # --- 2. Build Dynamic Filters ---
        filter_sql = """
            (target_account_holder_id = %s OR actor_user_id = (
                SELECT user_id FROM account_holders WHERE id = %s
            ))
        """
        params = [account_holder_id, account_holder_id]

        # Add Date Range filter if both are provided
        if start_date_str and end_date_str:
            try:
                # Replace 'Z' with +00:00 for ISO compatibility
                start = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                filter_sql += " AND date_created BETWEEN %s AND %s"
                params.extend([start, end])
            except ValueError:
                return _error_response(400, "Invalid date format. Use ISO-8601.")

        # Add Name Search
        if search_name:
            filter_sql += " AND message ILIKE %s"
            params.append(f"%{search_name}%")

        # Add Plate Search
        if search_plate:
            filter_sql += " AND message ILIKE %s"
            params.append(f"%{search_plate}%")

        # --- 3. Execute Count and Fetch ---
        cur.execute(f"SELECT COUNT(*) FROM logs WHERE {filter_sql}", tuple(params))
        total = cur.fetchone()["count"]

        fetch_sql = f"""
            SELECT * FROM logs
            WHERE {filter_sql}
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(fetch_sql, tuple(params + [page_size, offset]))
        logs = cur.fetchall()

    return _success_response(200, {
        "account_holder_id": account_holder_id,
        "logs": process_db_results(logs),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    })