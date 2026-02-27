import json
import psycopg2
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log, get_user_privileges_for_estate, get_user_privileges_for_personal_info, get_user_privileges_for_account_holder,send_email
import random
from datetime import datetime, timedelta
from middleware import verify_token
import math

def create_sub_account(conn, body, event):
    parent_account_holder_id = body.get("parent_account_holder_id")
    child_email            = body.get("email")
    if not parent_account_holder_id:
        return _error_response(400, "Missing 'parent_account_holder_id'.")
    otp = str(random.randint(100000, 999999))
    required_fields = ["name", "id_type", "id_num", "contact"]
    missing = [f for f in required_fields if not body.get(f)]
    if missing:
        return _error_response(400, f"Missing required fields: {', '.join(missing)}.")
    name = body.get("name")
    id_type = body.get("id_type")
    id_num = body.get("id_num")
    contact = body.get("contact")
    payload, error = verify_token(event)
    if error:
        return error
    caller_user_id = payload.get("user_id")
    is_admin       = payload.get("is_admin", False)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ah.id               AS account_holder_id,
                       ah.user_id         AS parent_user_id,
                       ah.house_address,
                       pi.estate_id
                FROM   account_holders ah
                JOIN   personal_info  pi ON pi.id = ah.personal_info_id
                WHERE  ah.id = %s
            """, (parent_account_holder_id,))

            parent = cur.fetchone()
            if not parent:
                return _error_response(404, "Parent account holder not found.")

            estate_id    = parent["estate_id"]
            house_address = parent["house_address"]
            parent_user_id = parent["parent_user_id"]
            is_owner = (caller_user_id == parent_user_id)
            has_priv  = False
            if not (is_owner or is_admin):
                privs =get_user_privileges_for_account_holder(cur, parent_user_id, parent_account_holder_id, is_admin = False)
                has_priv = privs and privs.can_manage_sub_users()  
            if not (is_owner or has_priv or is_admin):
                return _error_response(403, "You do not have privileges to create sub-accounts for this parent.")
            cur.execute("SELECT id FROM account_types WHERE name = 'SUB_USER'")
            row = cur.fetchone()
            if not row:
                return _error_response(500, "Default account type 'SUB_USER' not found.")
            account_type_id = row["id"]
            cur.execute("SELECT id FROM access_groups WHERE estate_id = %s AND name = 'REGULAR'", (estate_id,))
            row = cur.fetchone()
            if not row:
                return _error_response(500, "Default access group 'REGULAR' not found.")
            access_group_id = row["id"]
            cur.execute("""
                SELECT 1
                FROM   account_holders ah
                JOIN   personal_info pi ON pi.id = ah.personal_info_id
                WHERE  pi.contact = %s
                AND    pi.estate_id = %s
            """, (contact, estate_id))
            if cur.fetchone():
                return _error_response(409, "User already has an account in this estate.")
            try:
                cur.execute("""
                    INSERT INTO personal_info (estate_id, name, id_type, id_num, contact, account_type_id, access_group_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    estate_id,
                    name,
                    id_type,
                    id_num,
                    contact,
                    account_type_id,
                    access_group_id
                ))
                personal_info_id = cur.fetchone()["id"]

                cur.execute("""
                    INSERT INTO pending_account_holders (email, owner_account_holder_id, personal_info_id, house_address, otp, otp_generated_at)
                    VALUES (%s, %s, %s, %s, %s,  NOW() + INTERVAL '30 minutes')
                    RETURNING id
                """, (child_email, parent_account_holder_id,personal_info_id, house_address,otp))
                pending_holder_id = cur.fetchone()["id"]
            except psycopg2.errors.UndefinedTable as e:
                # Table not yet migrated – ignore
                conn.rollback()  # clear error state
                return _error_response(500, f"Database configuration error: {e}")
            
            subject = 'ACCESS ACCOUNT'
            message = (
                "You have been added as a member of house in house_address.\n"
                f"Activate this account using this one time password: {otp}.\n OTP expires in 30 minutes.\n"
                "Note that you need to download the app through "" on playstore and "" on appstore and sign-up."
            )
            send_email(child_email, subject, message)
            log(conn, "SUB_ACCOUNT_CREATION", f"Sub-account created for parent {parent_account_holder_id}", caller_user_id, parent_account_holder_id, estate_id)
            conn.commit()

        return _success_response(201, {
            "message": "Sub-account created successfully.",
            "sub_account": {
                  #"parent_account_holder_id": parent_account_holder_id,
                  "email" : child_email,
                  "pending_holder_id": pending_holder_id,
                  "personal_info_id": personal_info_id,
            #     "user_id": child_user_id,
            #     "estate_id": estate_id,
            #     "house_address": house_address
                  "phone_number": contact
            }
        })

    except Exception as e:
        conn.rollback()
        return _error_response(500, f"An error occurred: {e}")
    
def verify_otp(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    user_id = payload.get("user_id")
    input_otp = body.get("otp")
    personal_info_id =body.get("personal_info_id")
    name = body.get("name")
    if not input_otp or not personal_info_id:
        return _error_response(400, "Missing OTP or personal_info_id.")
   
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, otp, otp_generated_at FROM pending_account_holders WHERE personal_info_id = %s
            """, 
            (personal_info_id,))
            
        row = cur.fetchone()

        if not row:
            return _error_response(404, "No Otp found for this user.")
        if row["otp"] != input_otp:
            return _error_response(401, "Invalid OTP.")
        if row["otp_generated_at"] < datetime.utcnow():
            return _error_response(401, "OTP expired.")
        pending_holder_id = row["id"] 

        cur.execute("""
            INSERT INTO account_holders (personal_info_id, house_address, owner_account_holder_id,  user_id, is_active ) 
            SELECT pah.personal_info_id, pah.house_address, pah.owner_account_holder_id, %s, true       
            FROM pending_account_holders pah 
            WHERE pah.id = %s 
            RETURNING id
        """, (user_id,pending_holder_id)) # Pass the user_id value as a parameter tuple
        cur.execute("""
        DELETE FROM pending_account_holders WHERE id = %s; """,(pending_holder_id,))
    
        log(conn, "SUB_USER_REGISTRATION", f"Household Member '{name}' registered", user_id, None, None)

        conn.commit()

    return _success_response(201, {"message": "Account verified and created successfully.", "user_id": user_id})

def create_personal_info_privilege_link(conn, body, event):
    # 1.  Authentication / basic validation
    payload, error = verify_token(event)
    if error:
        return error

    actor_user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id = body.get("personal_info_id")
    privilege_id = body.get("privilege_ids")

    if not personal_info_id or not privilege_id:
        return _error_response(400, "Missing 'personal_info_id' or 'privilege_id'.")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 2. Ensure personal_info exists (and get estate)
        cur.execute("SELECT estate_id FROM personal_info WHERE id = %s", (personal_info_id,))
        row = cur.fetchone()
        if not row:
            return _error_response(404, "Personal info not found.")
        estate_id = row["estate_id"]

        # 3. Privilege gate (skip if global admin)
        if not is_admin:
            priv_ctx = get_user_privileges_for_estate(cur, actor_user_id, estate_id, is_admin=False)
            if not (priv_ctx and priv_ctx.can_manage_accounts()):
                return _error_response(403, "You do not have privileges to link privileges in this estate.")

        # 4. Verify privilege exists
        cur.execute("SELECT id FROM privileges WHERE id = %s", (privilege_id,))
        if not cur.fetchone():
            return _error_response(404, "Privilege not found.")

        # 5. Insert link idempotently
        cur.execute("""
            INSERT INTO personal_info_privilege_links (personal_info_id, privilege_id)
            VALUES (%s, %s)
            ON CONFLICT (personal_info_id, privilege_id) DO NOTHING
            RETURNING personal_info_id, privilege_id
        """, (personal_info_id, privilege_id))

        if not cur.fetchone():
            return _error_response(409, "Privilege already linked to this personal info.")

        # 6. Audit log & commit
        log(
            conn,
            "PERSONAL_INFO_PRIVILEGE_LINK",
            f"Linked privilege '{privilege_id}' to personal_info '{personal_info_id}'",
            actor_user_id,
            None,
            estate_id,
        )

        conn.commit()

    return _success_response(201, {"message": "Privilege linked successfully."})

def assign_selected_privileges_to_personal_info(conn, body, event):                                                       
    """                                                                                                                   
    Grant *multiple* privileges (subset chosen in UI) to one person.                                                      
                                                                                                                        
    Body:                                                                                                                 
        personal_info_id : int                                                                                            
        privilege_ids    : list[int]                                                                                      
    """                                                                                                                   
    payload, error = verify_token(event)                                                                                  
    if error:                                                                                                             
        return error                                                                                                      
                                                                                                                           
    actor_id   = payload.get("user_id")                                                                                   
    is_admin   = payload.get("is_admin", False)                                                                           
    personal_info_id = body.get("personal_info_id")                                                                       
    privilege_ids    = body.get("privilege_ids") or []  
    parent_account_holder_id = body.get("parent_account_holder_id")                                                                  
                                                                                                                           
    if not personal_info_id or not privilege_ids:                                                                         
        return _error_response(400, "personal_info_id & privilege_ids required")                                          
                                                                                                                           
    with conn.cursor(cursor_factory=RealDictCursor) as cur:                                                               
         # 1.  Resolve estate & security-check -------------                                                               
        cur.execute("SELECT estate_id FROM personal_info WHERE id=%s",                                                    
                     (personal_info_id,))                                                                                  
        row = cur.fetchone()                                                                                              
        if not row:                                                                                                       
            return _error_response(404, "Personal info not found")                                                        
                                                                                                                           
        estate_id = row["estate_id"]                                                                                      
        if not is_admin:                                                                                                  
            pc = get_user_privileges_for_account_holder(cur, actor_id, parent_account_holder_id, is_admin=False)                                                 
        if not (pc and pc.can_manage_sub_users()):                                                                     
            return _error_response(403, "user cannot manage sub_user")                                                    
                                                                                                                        
         # 2.  Optional – ensure *each* privilege really exists                                                            
        cur.execute(                                                                                                      
             "SELECT id FROM privileges WHERE id = ANY(%s)", (privilege_ids,))                                             
        found = {r["id"] for r in cur.fetchall()}                                                                         
        missing = set(privilege_ids) - found                                                                              
        if missing:                                                                                                       
            return _error_response(                                                                                       
                404, f"Unknown privilege ids: {sorted(missing)}")                                                         
                                                                                                                           
         # 3.  Bulk insert (idempotent) ---------------------                                                              
        cur.executemany(                                                                                                  
             """                                                                                                           
             INSERT INTO personal_info_privilege_links (personal_info_id, privilege_id)                                    
             VALUES (%s, %s)                                                                                               
             ON CONFLICT (personal_info_id, privilege_id) DO NOTHING                                                       
             """,                                                                                                          
             [(personal_info_id, pid) for pid in privilege_ids],                                                           
         )                                                                                                                 
                                                                                                                           
        log(conn,                                                                                                         
            "PERSONAL_INFO_PRIVILEGE_BULK_LINK",                                                                          
            f"Assigned privileges {privilege_ids} to personal_info {personal_info_id}",                                   
            actor_id, None, estate_id)                                                                                    
                                                                                                                        
        conn.commit()                                                                                                     
                                                                                                                        
    return _success_response(201, {                                                                                       
        "message": "Privileges assigned",                                                                                 
        "personal_info_id": personal_info_id,                                                                             
        "privilege_ids": privilege_ids                                                                                    
    })                                                                                                                    
                  
def send_sub_user_otp(conn, body, event):
    payload, error = verify_token(event)                                                                                  
    if error:                                                                                                             
        return error                                                                                                      
                                                                                                                            
    pending_holder_id = body.get("pending_holder_id")
    email = body.get("email")
    otp = str(random.randint(100000, 999999))
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            UPDATE pending_account_holders SET otp= %s, otp_generated_at = NOW() + INTERVAL '30 minutes'
            WHERE id = %s
        """, (otp, pending_holder_id))
        conn.commit()
    title = 'Your OTP Code'
    message =f"Your OTP is: {otp}."
    send_email(email, title, message)

    return _success_response(200, {
        "message": "A new OTP has been sent to your email.",
        
    })
    
def update_sub_account_privileges(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    actor_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    personal_info_id          = body.get("personal_info_id")
    privilege_ids             = body.get("privilege_ids") or []
    parent_account_holder_id  = body.get("parent_account_holder_id")

    if not personal_info_id or privilege_ids is None:
        return _error_response(400, "personal_info_id & privilege_ids required")

    # Ensure list contains unique ints
    try:
        privilege_ids = list({int(pid) for pid in privilege_ids})
    except (TypeError, ValueError):
        return _error_response(400, "privilege_ids must be a list of ints")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Resolve estate for later privilege checks / logging
        cur.execute("SELECT estate_id FROM personal_info WHERE id=%s", (personal_info_id,))
        row = cur.fetchone()
        if not row:
            return _error_response(404, "Personal info not found")
        estate_id = row["estate_id"]

        # ----- Security gate -------------------------------------------------
        if not is_admin:
            pc = get_user_privileges_for_account_holder(cur, actor_id, parent_account_holder_id, is_admin=False)
            if not (pc and pc.can_manage_sub_users()):
                return _error_response(403, "User cannot manage sub_user privileges")

        # Verify each privilege exists (fail fast if any unknown)
        cur.execute("SELECT id FROM privileges WHERE id = ANY(%s)", (privilege_ids,))
        found_ids = {r["id"] for r in cur.fetchall()}
        missing = set(privilege_ids) - found_ids
        if missing:
            return _error_response(404, f"Unknown privilege ids: {sorted(missing)}")

        # Current set on record
        cur.execute("""
            SELECT privilege_id FROM personal_info_privilege_links
            WHERE personal_info_id = %s
        """, (personal_info_id,))
        current = {r["privilege_id"] for r in cur.fetchall()}

        to_insert = set(privilege_ids) - current

        # Bulk insert remaining
        if to_insert:
            cur.executemany(
                """
                INSERT INTO personal_info_privilege_links (personal_info_id, privilege_id)
                VALUES (%s, %s)
                ON CONFLICT (personal_info_id, privilege_id) DO NOTHING
                """,
                [(personal_info_id, pid) for pid in to_insert],
            )

        log(
            conn,
            "PERSONAL_INFO_PRIVILEGE_UPDATE",
            f"Added privileges {sorted(privilege_ids)} to personal_info {personal_info_id}",
            actor_id,
            None,
            estate_id,
        )
        conn.commit()

    return _success_response(
        200,
        {
            "message": "Privileges updated",
            "personal_info_id": personal_info_id,
            "privilege_ids": privilege_ids,
        },
    )

def delete_sub_account(conn, body, event):
    """
    Permanently (or soft-) delete a sub-account.

    Expected body:
        sub_account_holder_id : int – The account_holders.id of the sub-user
    """
    payload, error = verify_token(event)
    if error:
        return error

    actor_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)

    sub_account_holder_id = body.get("sub_account_holder_id")
    if not sub_account_holder_id:
        return _error_response(400, "sub_account_holder_id required")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Fetch owner relationship & estate for security checks & logging
        cur.execute(
            """
            SELECT ah_sub.personal_info_id, ah_sub.owner_account_holder_id, ah_owner.user_id AS owner_user_id,
                   ah_sub.house_address, pi.estate_id
            FROM   account_holders ah_sub
            JOIN   account_holders ah_owner ON ah_sub.owner_account_holder_id = ah_owner.id
            JOIN   personal_info pi        ON ah_sub.personal_info_id        = pi.id
            WHERE  ah_sub.id = %s
            """,
            (sub_account_holder_id,),
        )
        row = cur.fetchone()
        if not row:
            return _error_response(404, "Sub-account not found")

        estate_id               = row["estate_id"]
        owner_user_id           = row["owner_user_id"]
        personal_info_id        = row["personal_info_id"]

        if not is_admin and actor_id != owner_user_id:
            priv = get_user_privileges_for_account_holder(cur, actor_id, row["owner_account_holder_id"], is_admin=False)
            if not (priv and priv.can_manage_sub_users()):
                return _error_response(403, "You do not have permission to delete this sub-account")
        log(
            conn,
            "SUB_ACCOUNT_DELETE",
            f"Sub-account {sub_account_holder_id} deactivated by user {actor_id}",
            actor_id,
            sub_account_holder_id,
            estate_id,
        )
        
        cur.execute(                                                                                                                                                    
            "DELETE FROM account_holders WHERE id = %s", (sub_account_holder_id,),)  
        cur.execute(                                                                                                                                                    
            "DELETE FROM personal_info WHERE id = %s", (personal_info_id,),)                                
        # Optionally, also revoke all privileges (cleanup)
        cur.execute(
            "DELETE FROM personal_info_privilege_links WHERE personal_info_id = %s",(personal_info_id,),)
        
       
        conn.commit()

    return _success_response(200, {"message": "Sub-account deleted (deactivated)"})

def get_sub_accounts(conn, event):
    # 1. AUTHENTICATION: Get the trusted caller ID
    payload, error = verify_token(event)
    if error:
        return error
    
    caller_user_id = payload.get("user_id")
    is_admin = payload.get("is_admin", False)
    if not caller_user_id:
        return _error_response(401, "Invalid token or user ID.")
    path_params = event.get("pathParameters", {})
    estate_id = path_params.get("estate_id")
    user_id = path_params.get("user_id")
    if not is_admin and str(caller_user_id) != user_id:
        return _error_response(403, "You do not have permission...")
    query_params = event.get("queryStringParameters") or {}
    try:
        page = int(query_params.get("page", 1))
        limit = int(query_params.get("page_size", 20))
        if page < 1 or limit < 1 or limit > 100:
            raise ValueError
    except (ValueError, TypeError):
        return _error_response(400, "Invalid 'page' or 'limit'. Must be numbers.")
    offset = (page - 1) * limit
    sub_accounts = []
    total_items = 0
    # 2. EXECUTION: Run the query
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
        # This query finds all sub-accounts (ah_sub) whose owner (ah_owner)
        # has a user_id matching the caller.
            cur.execute("""
                SELECT 
                    ah_sub.id, 
                    ah_sub.user_id, 
                    ah_sub.owner_account_holder_id, 
                    ah_sub.house_address,
                    p.name,
                    p.contact,
                    p.id_type,
                    p.id_num,
                    p.id AS personal_info_id,
                    u.email
                FROM 
                    account_holders ah_sub -- This is the sub-account
                JOIN 
                    account_holders ah_owner ON ah_sub.owner_account_holder_id = ah_owner.id -- This is the owner
                JOIN 
                    personal_info p ON ah_sub.personal_info_id = p.id
                JOIN 
                    users u ON ah_sub.user_id = u.id
                WHERE 
                    ah_owner.user_id = %s AND p.estate_id = %s -- Match the owner's user_id to the caller
                -- You might want to add an ORDER BY clause:
                ORDER BY p.name ASC  LIMIT %s OFFSET %s
            """,(user_id, estate_id,limit, offset))
            sub_accounts = cur.fetchall()
            
        except (Exception, psycopg2.DatabaseError) as e:
            conn.rollback()
            print(f"Database error while fetching sub-accounts: {e}") # For your logs
            return _error_response(500, "An error occurred while fetching sub-accounts.")
    total_pages = 1
    if total_items > 0:
        total_pages = math.ceil(total_items / limit)
    
    pagination_data = {
        "total_items": total_items,
        "total_pages": total_pages,
        "current_page": page,
        "items_per_page": limit
    }
    # 3. RESPONSE: Return the list (it will be an empty list [] if none are found)
    return _success_response(200, {"sub_accounts": sub_accounts,"pagination": pagination_data})

