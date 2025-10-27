import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges_for_estate, get_user_privileges_for_personal_info, get_user_privileges_for_account_holder,send_email_gmail, get_user_privileges_for_personal_info
import random
from datetime import datetime, timedelta
from middleware import verify_token

def update_account(conn, body, event):    
    payload, error = verify_token(event)
    if error:
        return error
    
    caller_user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False) # Default to False if not present
    
    if not caller_user_id:
        return _error_response(401, "Invalid token or user ID.")

    # 2. INPUT: Get what to update and which account to target
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    account_holder_id_to_edit = body.get("account_holder_id")
    if not account_holder_id_to_edit:
        # Fixed the error message to match the check
        return _error_response(400, "Missing 'account_holder_id' in request body.")
    
    if all(v is None for v in [name, id_type, id_num, contact]):
        return _error_response(400, "No fields provided to update.")
    # 4. EXECUTION: Run the single, atomic, and secure query
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute( """
            UPDATE personal_info p
            SET 
                name = COALESCE(%s, p.name), 
                id_type = COALESCE(%s, p.id_type), 
                id_num = COALESCE(%s, p.id_num), 
                contact = COALESCE(%s, p.contact)
            FROM 
                account_holders ah_sub -- The account we are editing
            LEFT JOIN 
                account_holders ah_owner ON ah_sub.owner_account_holder_id = ah_owner.id -- Find its owner
            WHERE 
                p.id = ah_sub.personal_info_id  -- Link p to ah_sub
            AND ah_sub.id = %s               -- Target the specific account
            AND (
                ah_sub.user_id = %s           -- CASE 1: Caller is the account's user
                OR
                ah_owner.user_id = %s         -- CASE 2: Caller is the account's OWNER's user
                OR
                %s = True                     -- CASE 3: Caller is an admin 
                )
            RETURNING 
                ah_sub.id AS matched_account_holder_id,
                ah_sub.user_id AS matched_user_id,
                ah_sub.estate_id; 
        """, (
            name, id_type, id_num, contact,  # For COALESCE
            account_holder_id_to_edit,       # For ah_sub.id = %s
            caller_user_id,                  # For ah_sub.user_id = %s
            caller_user_id,                  # For ah_owner.user_id = %s
            is_admin                         # For %s = True
        ))
        result = cur.fetchone()

        if not result:
            conn.rollback()
            # This is now our *only* permission check. If no rows are
            # returned, the user had no permission or the ID was wrong.
            return _error_response(404, "Account holder not found or you do not have permission to edit this user.")

        # Log the action
        log(conn, "ACCOUNT_UPDATE", f"Account updated {result['matched_account_holder_id']}", caller_user_id, None, result["estate_id"])
        
        conn.commit()

    return _success_response(200, {"message": "Account and related personal info updated successfully."})