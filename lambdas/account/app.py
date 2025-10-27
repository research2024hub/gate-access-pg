import json
import psycopg2
from handlers.account import (
    signup, signupAdmin,
    change_account_type, deactivate_account, activate_account, delete_account, 
    get_estate_accounts, generate_account_otp, verify_account_otp,create_sub_account,verify_otp,create_personal_info_privilege_link,
    assign_selected_privileges_to_personal_info,send_sub_user_otp
    # confirm_signup
)
from handlers.subaccount import (update_account,get_sub_accounts)

import os
from utils import _error_response

def lambda_handler(event, context):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return _error_response(500, "DATABASE_URL not set")

    try:
        conn = psycopg2.connect(db_url)

        raw_body = event.get("body", "")
        body = json.loads(raw_body) if raw_body else {}

        path = event.get("path", "")
        http_method = event.get("httpMethod", "").upper()

        if http_method == "GET":
            if path.startswith("/account/estate/"):
                return get_estate_accounts(conn, event)
            elif path.startswith("/account/sub_user/getsub/"):
                return  get_sub_accounts(conn, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "POST":
            if path == "/account/signup":
                return signup(conn, body)
            elif path == "/account/admin-signup":
                return signupAdmin(conn, body)
            # elif path == "/account/signup/confirm":
            #     return confirm_signup(conn, body)
            elif path == "/account/change_type":
                return change_account_type(conn, body, event)
            elif path == "/account/deactivate":
                return deactivate_account(conn, body, event)
            elif path == "/account/activate":
                return activate_account(conn, body, event)
            elif path == "/account/sub_user/create":
                return create_sub_account(conn, body, event)
            elif path == "/account/sub_user/select_privilege":
                return assign_selected_privileges_to_personal_info(conn, body, event)
            elif path == "/account/sub_user/create_privilege":
                return create_personal_info_privilege_link(conn, body, event)
            elif path == "/account/sub_user/verify":
                return verify_otp(conn, body, event)
            elif path == "/account/sub_user/otp":
                return send_sub_user_otp(conn, body, event)
            elif path == "/account/update":
                return update_account(conn, body, event)
            
            elif path == "/account/otp/generate":
                return generate_account_otp(conn, body, event)
            elif path == "/account/otp/verify":
                return verify_account_otp(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        elif http_method == "DELETE":
            if path == "/account/delete":
                return delete_account(conn, body, event)
            else:
                return _error_response(404, f"Path '{path}' not found.")
        # elif http_method == "GET":
        #     if path.startswith("/account/details/"):
        #         if path == "/account/details/me":
        #             return get_own_accounts(conn, event)
        #         else:
        #             return get_user_accounts(conn, event)
        #     else:
        #         return _error_response(404, f"Path '{path}' not found.")
        else:
            return _error_response(405, f"Method {http_method} not supported.")

    except Exception as e:
        return _error_response(500, str(e))
    finally:
        if 'conn' in locals():
            conn.close()
