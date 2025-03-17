from datetime import datetime
import json
import requests
import firebase_admin
from firebase_admin import credentials
from firebase_admin import messaging

Collection_Id='gate_app_collection_id'
cred = credentials.Certificate("./gate-access-dev-firebase-adminsdk-jk7hy-ebbdd45791.json")
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
            VALUES (%s, %s, %s, %s)
            RETURNING id, estate_id, actor_user_id, target_account_holder_id, type, message, date_created
        """, (estate_id, actor_user_id, target_account_holder_id, type, message))

        new_log = cur.fetchone()

    return _success_response(201, {"log": process_db_results([new_log])})
