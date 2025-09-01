from datetime import datetime
import json
import requests
import firebase_admin
from firebase_admin import credentials
from firebase_admin import messaging
from psycopg2.extras import RealDictCursor

Collection_Id='gate_app_collection_id'
cred = credentials.Certificate("/opt/python/gate-access-dev-firebase-adminsdk-jk7hy-ebbdd45791.json")
firebase_admin.initialize_app(cred)

def _error_response(status_code, message):
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message})
    }

def _success_response(status, data):
    """Returns a success response."""
    return {
        "statusCode": status,
        "body": json.dumps(data)
    }

def process_db_results(results):
    """
    Converts database query results into JSON-serializable format.
    Handles datetime serialization and ensures all data is JSON-friendly.

    Args:
        results (list): List of dictionaries (RealDictCursor) or tuples from DB query.

    Returns:
        list: A processed list where datetime fields are converted to strings.
    """
    processed_results = []

    for row in results:
        # Ensure we handle both dict-based (RealDictCursor) and tuple-based results
        if isinstance(row, dict):
            processed_row = {
                key: (value.isoformat() if isinstance(value, datetime) else value)
                for key, value in row.items()
            }
        elif isinstance(row, tuple):
            processed_row = [
                value.isoformat() if isinstance(value, datetime) else value
                for value in row
            ]
        else:
            processed_row = row  # In case of unexpected formats

        processed_results.append(processed_row)

    return processed_results

def send_message(phone_number, message):
    print("I am sending the message to ", phone_number)
    print("The message is ", message)
    url = "http://52.89.222.13/tfsg/public/api/send"
    json_data = {"api_key": "ebow:baby",
                 "merchant_id": 1,
                 "message": message,
                 "recipients": [phone_number]
                }
    response = requests.post(url, json=json_data)

    # Print the response
    print("Status Code for sending message:", response.status_code)
    print("Response Body for sending message:", response.text)

def notify_user(user_id, title, message):
    print("The topic chosen is ", user_id)
    try:
        message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=message
        ),
        topic=user_id
        )
        response = messaging.send(message)
        print('Successfully sent message:', response)
        return True
    except Exception as e:
        print("There is an error notifying the resident ", e)
        return False
    
def log(conn, type, message, actor_user_id=None, target_account_holder_id=None, estate_id=None):
    """
    Creates a log entry for a specific estate.
    Only admins can access this data.
    """

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO logs (estate_id, actor_user_id, target_account_holder_id, type, message)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, estate_id, actor_user_id, target_account_holder_id, type, message, date_created
        """, (estate_id, actor_user_id, target_account_holder_id, type, message))

        new_log = cur.fetchone()

    return _success_response(201, {"log": process_db_results([new_log])})


class PrivilegeContext:
    """
    A helper class that encapsulates user privilege information for a specific account holder.
    Performs a single comprehensive query to get all privilege and estate information.
    """

    def __init__(self, cur, user_id, account_holder_id, is_admin=False):
        """
        Initialize privilege context with a single database query.

        Args:
            cur: Database cursor
            user_id: ID of the user making the request
            account_holder_id: ID of the account holder being acted upon
            is_admin: Whether the user is an admin
        """
        self.user_id = user_id
        self.account_holder_id = account_holder_id
        self.is_admin = is_admin
        self._privileges = None
        self._estate_info = None
        self._loaded = False

        # Load all privilege and estate information in one query
        self._load_privileges(cur)

    def _load_privileges(self, cur):
        """Load all privilege and estate information in a single query."""
        cur.execute("""
            WITH target_estate AS (
                SELECT pi.estate_id, es.name as estate_name
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN estates es ON es.id = pi.estate_id
                WHERE ah.id = %s
            ),
            user_privileges AS (
                SELECT
                    ah.id as user_account_holder_id,
                    ah.user_id = %s as is_same_person,
                    bool_or(pv.name = 'MANAGE_ALL') as can_manage_all,
                    bool_or(pv.name = 'MANAGE_GUESTS') as can_manage_guests,
                    bool_or(pv.name = 'MANAGE_VEHICLES') as can_manage_vehicles,
                    bool_or(pv.name = 'CREATE_VEHICLES') as can_create_vehicles
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                LEFT JOIN account_types act ON pi.account_type_id = act.id
                LEFT JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                LEFT JOIN privileges pv ON atpl.privilege_id = pv.id
                WHERE ah.user_id = %s
                  AND ah.is_active = TRUE
                  AND pi.estate_id = (SELECT estate_id FROM target_estate)
                GROUP BY ah.id, ah.user_id
            )
            SELECT
                te.estate_id,
                te.estate_name,
                COALESCE(up.is_same_person, FALSE) as is_same_person,
                COALESCE(up.can_manage_all, FALSE) as can_manage_all,
                COALESCE(up.can_manage_guests, FALSE) as can_manage_guests,
                COALESCE(up.can_manage_vehicles, FALSE) as can_manage_vehicles,
                COALESCE(up.can_create_vehicles, FALSE) as can_create_vehicles,
                EXISTS(SELECT 1 FROM target_estate) as account_holder_exists
            FROM target_estate te
            LEFT JOIN user_privileges up ON TRUE
        """, (self.account_holder_id, self.user_id, self.user_id))

        result = cur.fetchone()

        if result and result["account_holder_exists"]:
            self._estate_info = {
                "estate_id": result["estate_id"],
                "estate_name": result["estate_name"]
            }
            self._privileges = {
                "is_same_person": result["is_same_person"],
                "can_manage_all": result["can_manage_all"],
                "can_manage_guests": result["can_manage_guests"],
                "can_manage_vehicles": result["can_manage_vehicles"],
                "can_create_vehicles": result["can_create_vehicles"]
            }
        else:
            self._estate_info = None
            self._privileges = None

        self._loaded = True

    @property
    def is_valid(self):
        """Check if the account holder exists and we have valid data."""
        return self._loaded and self._estate_info is not None

    @property
    def estate_id(self):
        """Get the estate ID."""
        return self._estate_info["estate_id"] if self._estate_info else None

    @property
    def estate_name(self):
        """Get the estate name."""
        return self._estate_info["estate_name"] if self._estate_info else None

    def can_manage_guests(self):
        """Check if user can manage guests."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_guests"] or
                self._privileges["is_same_person"])

    def can_manage_vehicles(self):
        """Check if user can manage vehicles."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_vehicles"])

    def can_create_vehicles(self):
        """Check if user can create vehicles (for guests or themselves)."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_vehicles"] or
                self._privileges["can_create_vehicles"])


def get_user_privileges(cur, user_id, account_holder_id, is_admin=False):
    """
    Helper function to get user privileges for a specific account holder.
    Returns a PrivilegeContext object with all privilege and estate information.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        account_holder_id: ID of the account holder being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information

    Example usage:
        privileges = get_user_privileges(cur, user_id, account_holder_id, is_admin)

        if not privileges.is_valid:
            return _error_response(400, "Account holder not found")

        if not privileges.can_manage_guests():
            return _error_response(403, "Insufficient privileges")

        estate_id = privileges.estate_id
        estate_name = privileges.estate_name
    """
    return PrivilegeContext(cur, user_id, account_holder_id, is_admin)
