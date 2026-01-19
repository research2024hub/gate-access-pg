from datetime import datetime
import json
import requests
import firebase_admin
from firebase_admin import credentials
from firebase_admin import messaging
from psycopg2.extras import RealDictCursor
import boto3
import smtplib
from email.mime.text import MIMEText

Collection_Id='gate_app_collection_id'
cred = credentials.Certificate("/opt/python/gate-access-dev-firebase-adminsdk-jk7hy-ebbdd45791.json")
firebase_admin.initialize_app(cred)
s3 = boto3.client('s3', region_name='eu-west-1')

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
    
def generate_presigned_url(filename,bucket_name):
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': "lp-images/" + filename},
        #ExpiresIn=3600  # URL valid for 1 hour
    )
    
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

def send_gmail(to_email, subject, message):
    gmail_user = 'itcresearch340@gmail.com'  # e.g. "yourname@gmail.com"
    gmail_app_password = 'lwkpuzjpezobxyny'  # the 16-char app password

    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = gmail_user
    msg['To'] = to_email

    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(gmail_user, gmail_app_password)
    server.send_message(msg)
    server.quit()
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
            WITH target_account_holder AS (
                SELECT
                    ah.id,
                    ah.user_id,
                    pi.estate_id,
                    es.name as estate_name
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                JOIN estates es ON es.id = pi.estate_id
                WHERE ah.id = %s
            ),
            user_privileges AS (
                SELECT
                    ah.id as user_account_holder_id,
                    bool_or(pv.name = 'MANAGE_ALL') as can_manage_all,
                    bool_or(pv.name = 'MANAGE_GUESTS') as can_manage_guests,
                    bool_or(pv.name = 'CREATE_GUESTS') as can_create_guests,
                    bool_or(pv.name = 'MANAGE_VEHICLES') as can_manage_vehicles,
                    bool_or(pv.name = 'CREATE_VEHICLES') as can_create_vehicles,
                    bool_or(pv.name = 'MANAGE_GATES') as can_manage_gates,
                    bool_or(pv.name = 'MANAGE_ACCOUNTS') as can_manage_accounts,
                    bool_or(pv.name = 'MANAGE_EVENTS') as can_manage_events,
                    bool_or(pv.name = 'CREATE_EVENTS') as can_create_events,
                    bool_or(pv.name = 'MANAGE_ACCESS') as can_manage_access,
                    bool_or(pv.name = 'MANAGE_DEVICES') as can_manage_devices,
                    bool_or(pv.name = 'VIEW_LOGS') as can_view_logs,
                    bool_or(pv.name = 'MANAGE_SUB_USERS') as can_manage_sub_users,
                    bool_or(pv.name = 'CREATE_SUB_USERS') as can_create_sub_users
                FROM account_holders ah
                JOIN personal_info pi ON ah.personal_info_id = pi.id
                LEFT JOIN account_types act ON pi.account_type_id = act.id
                LEFT JOIN account_type_privilege_links atpl ON act.id = atpl.account_type_id
                LEFT JOIN personal_info_privilege_links pipl ON pipl.personal_info_id = pi.id                                                                                                       
                LEFT JOIN privileges pv ON pv.id IN (atpl.privilege_id, pipl.privilege_id)
                WHERE ah.user_id = %s
                  AND ah.is_active = TRUE
                  AND pi.estate_id = (SELECT estate_id FROM target_account_holder)
                GROUP BY ah.id
            )
            SELECT
                tah.estate_id,
                tah.estate_name,
                tah.user_id = %s as is_same_person,
                COALESCE(up.can_manage_all, FALSE) as can_manage_all,
                COALESCE(up.can_manage_guests, FALSE) as can_manage_guests,
                COALESCE(up.can_manage_vehicles, FALSE) as can_manage_vehicles,
                COALESCE(up.can_create_guests, FALSE) as can_create_guests,
                COALESCE(up.can_create_vehicles, FALSE) as can_create_vehicles,
                COALESCE(up.can_manage_gates, FALSE) as can_manage_gates,
                COALESCE(up.can_manage_accounts, FALSE) as can_manage_accounts,
                COALESCE(up.can_manage_events, FALSE) as can_manage_events,
                COALESCE(up.can_create_events, FALSE) as can_create_events,
                COALESCE(up.can_manage_access, FALSE) as can_manage_access,
                COALESCE(up.can_manage_devices, FALSE) as can_manage_devices,
                COALESCE(up.can_view_logs, FALSE) as can_view_logs,
                COALESCE(up.can_manage_sub_users, FALSE) as can_manage_sub_users,
                COALESCE(up.can_create_sub_users, FALSE) as can_create_sub_users,
                EXISTS(SELECT 1 FROM target_account_holder) as account_holder_exists
            FROM target_account_holder tah
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
                "can_create_guests": result["can_create_guests"],
                "can_manage_vehicles": result["can_manage_vehicles"],
                "can_create_vehicles": result["can_create_vehicles"],
                "can_manage_gates": result["can_manage_gates"],
                "can_manage_accounts": result["can_manage_accounts"],
                "can_manage_events": result["can_manage_events"],
                "can_create_events": result["can_create_events"],
                "can_manage_access": result["can_manage_access"],
                "can_manage_devices": result["can_manage_devices"],
                "can_view_logs": result["can_view_logs"],
                "can_manage_sub_users": result["can_manage_sub_users"],
                "can_create_sub_users": result["can_create_sub_users"]
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

    def can_manage_all(self):
        """Check if user has MANAGE_ALL privilege (super admin level)."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return self._privileges["can_manage_all"]

    def can_manage_guests(self):
        """Check if user can manage any guest in the estate."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_guests"])

    def can_create_guests(self):
        """Check if user can CREATE guests."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_guests"] or
                self._privileges["can_create_guests"])

    def can_manage_or_own_guests(self):
        """Check if user can RUD guests (manage any OR own their own)."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_guests"] or
                (self._privileges["can_create_guests"] and self._privileges["is_same_person"]))

    def can_manage_vehicles(self):
        """Check if user can manage any vehicle in the estate."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_vehicles"])

    def can_create_vehicles(self):
        """Check if user can CREATE vehicles."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_vehicles"] or
                self._privileges["can_create_vehicles"])

    def can_manage_or_own_vehicles(self):
        """Check if user can RUD vehicles (manage any OR own their own)."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_vehicles"] or
                (self._privileges["can_create_vehicles"] and self._privileges["is_same_person"]))

    def can_manage_gates(self):
        """Check if user can manage gates."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_gates"])

    def can_manage_accounts(self):
        """Check if user can manage accounts."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_accounts"])

    def can_manage_events(self):
        """Check if user can manage any event in the estate."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_events"])

    def can_create_events(self):
        """Check if user can CREATE events."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_events"] or
                self._privileges["can_create_events"])

    def can_manage_or_own_events(self):
        """Check if user can RUD events (manage any OR own their own)."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_events"] or
                (self._privileges["can_create_events"] and self._privileges["is_same_person"]))

    def can_manage_access_groups(self):
        """Check if user can manage access groups."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_access"])

    def can_manage_devices(self):
        """Check if user can manage devices."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_manage_devices"])

    def can_view_logs(self):
        """Check if user can view logs."""
        if self.is_admin:
            return True
        if not self._privileges:
            return False
        return (self._privileges["can_manage_all"] or
                self._privileges["can_view_logs"])
        
    def can_manage_sub_users(self):                                                                                                                                       
        if self.is_admin:                                                                                                                                                 
            return True                                                                                                                                                   
        if not self._privileges:                                                                                                                                          
            return False                                                                                                                                                  
        return (self._privileges["can_manage_all"] or                                                                                                                     
                self._privileges["can_manage_sub_users"] or 
                (self._privileges["can_create_sub_users"] and self._privileges["is_same_person"]))                                                                                                                
                                                        
        

    def can_manage_vehicle_for_person(self, cur, personal_info_id):
        """
        Check if user can manage vehicles for a specific person.
        Supports both direct ownership and guest relationships.
        """
        if self.is_admin:
            return True
        if not self._privileges:
            return False

        # Check if user has general vehicle management privileges
        if (self._privileges["can_manage_all"] or
            self._privileges["can_manage_vehicles"]):
            return True

        # Check if user can create vehicles and has relationship to this person
        if self._privileges["can_create_vehicles"]:
            cur.execute("""
                SELECT
                    EXISTS(SELECT 1 FROM personal_info pi
                        JOIN account_holders ah ON ah.personal_info_id = pi.id
                        WHERE ah.is_active = TRUE AND ah.user_id = %s AND pi.id = %s) AS for_myself,
                    EXISTS(SELECT 1 FROM personal_info pi
                        JOIN guests g ON g.personal_info_id = pi.id
                        JOIN account_holders ah ON ah.id = g.creator_id
                        WHERE ah.is_active = TRUE AND ah.user_id = %s AND pi.id = %s) AS for_my_guest
            """, (self.user_id, personal_info_id, self.user_id, personal_info_id))
            result = cur.fetchone()
            return result["for_myself"] or result["for_my_guest"]

        return False

    def can_view_vehicle_for_person(self, cur, personal_info_id):
        """
        Check if user can view vehicles for a specific person.
        More permissive than management - includes ownership.
        """
        # Can manage implies can view
        if self.can_manage_vehicle_for_person(cur, personal_info_id):
            return True

        # Check direct ownership even without CREATE_VEHICLES privilege
        cur.execute("""
            SELECT EXISTS(SELECT 1 FROM personal_info pi
                JOIN account_holders ah ON ah.personal_info_id = pi.id
                WHERE ah.is_active = TRUE AND ah.user_id = %s AND pi.id = %s) AS is_owner
        """, (self.user_id, personal_info_id))
        result = cur.fetchone()
        return result["is_owner"]

    def is_owner_of_account_holder(self, cur, target_account_holder_id):
        """Check if the user owns the target account holder."""
        cur.execute("""
            SELECT EXISTS(SELECT 1 FROM account_holders
                WHERE user_id = %s AND id = %s AND is_active = TRUE) AS is_owner
        """, (self.user_id, target_account_holder_id))
        result = cur.fetchone()
        return result["is_owner"]

    def is_creator_of_event(self, cur, event_id):
        """Check if the user created the event."""
        cur.execute("""
            SELECT EXISTS(SELECT 1 FROM events e
                JOIN account_holders ah ON e.creator_id = ah.id
                WHERE ah.user_id = %s AND e.id = %s AND ah.is_active = TRUE) AS is_creator
        """, (self.user_id, event_id))
        result = cur.fetchone()
        return result["is_creator"]
    

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


def get_user_privileges_for_vehicle(cur, user_id, vehicle_id, is_admin=False):
    """
    Helper function to get user privileges for vehicle operations.
    Resolves the account holder from the vehicle's personal_info.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        vehicle_id: ID of the vehicle being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If vehicle not found
    """
    # Get account holder from vehicle
    cur.execute("""
        SELECT COALESCE(ah.id, g.creator_id) as account_holder_id
        FROM vehicles v
        JOIN personal_info pi ON v.personal_info_id = pi.id
        LEFT JOIN account_holders ah ON pi.id = ah.personal_info_id
        LEFT JOIN guests g ON pi.id = g.personal_info_id
        WHERE v.id = %s
    """, (vehicle_id,))

    result = cur.fetchone()
    if not result:
        return None

    return PrivilegeContext(cur, user_id, result["account_holder_id"], is_admin)


def get_user_privileges_for_event(cur, user_id, event_id, is_admin=False):
    """
    Helper function to get user privileges for event operations.
    Resolves the account holder from the event's creator.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        event_id: ID of the event being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If event not found
    """
    # Get account holder from event
    cur.execute("""
        SELECT creator_id as account_holder_id
        FROM events
        WHERE id = %s
    """, (event_id,))

    result = cur.fetchone()
    if not result:
        return None

    return PrivilegeContext(cur, user_id, result["account_holder_id"], is_admin)


def get_user_privileges_for_gate(cur, user_id, gate_id, is_admin=False):
    """
    Helper function to get user privileges for gate operations.
    Uses any account holder in the same estate as the gate.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        gate_id: ID of the gate being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If gate not found or user has no account in that estate
    """
    # Get any account holder for the user in the same estate as the gate
    cur.execute("""
        SELECT ah.id as account_holder_id
        FROM gates g
        JOIN account_holders ah ON TRUE
        JOIN personal_info pi ON ah.personal_info_id = pi.id
        WHERE g.id = %s
          AND ah.user_id = %s
          AND ah.is_active = TRUE
          AND pi.estate_id = g.estate_id
        LIMIT 1
    """, (gate_id, user_id))

    result = cur.fetchone()
    if not result:
        return None

    return PrivilegeContext(cur, user_id, result["account_holder_id"], is_admin)


def get_user_privileges_for_estate(cur, user_id, estate_id, is_admin=False):
    """
    Helper function to get user privileges for estate-level operations.
    Uses any account holder for the user in the specified estate.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        estate_id: ID of the estate
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If user has no account in that estate
    """
    # Get any account holder for the user in this estate
    cur.execute("""
        SELECT ah.id as account_holder_id
        FROM account_holders ah
        JOIN personal_info pi ON ah.personal_info_id = pi.id
        WHERE ah.user_id = %s
          AND ah.is_active = TRUE
          AND pi.estate_id = %s
        LIMIT 1
    """, (user_id, estate_id))

    result = cur.fetchone()
    if not result:
        return None

    return PrivilegeContext(cur, user_id, result["account_holder_id"], is_admin)


def get_user_privileges_for_access_group(cur, user_id, access_group_id, is_admin=False):
    """
    Helper function to get user privileges for access group operations.
    Resolves the estate from the access group.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        access_group_id: ID of the access group being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If access group not found or user has no account in that estate
    """
    # Get estate from access group
    cur.execute("""
        SELECT estate_id FROM access_groups WHERE id = %s
    """, (access_group_id,))

    result = cur.fetchone()
    if not result:
        return None

    estate_id = result["estate_id"]
    return get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)


def get_user_privileges_for_personal_info(cur, user_id, personal_info_id, is_admin=False):
    """
    Helper function to get user privileges for personal info operations.
    Resolves the estate from the personal info.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        personal_info_id: ID of the personal info being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If personal info not found or user has no account in that estate
    """
    # Get estate from personal info
    cur.execute("""
        SELECT estate_id FROM personal_info WHERE id = %s
    """, (personal_info_id,))

    result = cur.fetchone()
    if not result:
        return None

    estate_id = result["estate_id"]
    return get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)


def get_user_privileges_for_account_holder(cur, user_id, account_holder_id, is_admin=False):
    """
    Helper function to get user privileges for account holder operations.
    Resolves the estate from the account holder.

    Args:
        cur: Database cursor
        user_id: ID of the user making the request
        account_holder_id: ID of the account holder being acted upon
        is_admin: Whether the user is an admin

    Returns:
        PrivilegeContext: Object containing all privilege and estate information
        None: If account holder not found or user has no account in that estate
    """
    # Get estate from account holder
    cur.execute("""
        SELECT pi.estate_id
        FROM account_holders ah
        JOIN personal_info pi ON ah.personal_info_id = pi.id
        WHERE ah.id = %s
    """, (account_holder_id,))

    result = cur.fetchone()
    if not result:
        return None

    estate_id = result["estate_id"]
    return get_user_privileges_for_estate(cur, user_id, estate_id, is_admin)
