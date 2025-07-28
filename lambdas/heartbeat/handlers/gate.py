import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log
from middleware import verify_token
import time
import boto3
ses_client = boto3.client('ses')
SENDER_EMAIL = "jagudogo@itconsortiumgh.com"
RECIPIENT_EMAILS = ["research@itconsortiumgh.com"]
THRESHOLD_SECONDS = 300  # Adjust based on your requirements


def monitor_heartbeat(conn):

    # Query all heartbeat records
    with conn.cursor() as cur:
        cur.execute("SELECT id, last_controller_heartbeat FROM gates")
        rows = cur.fetchall()

        current_time = int(time.time())

        for row in rows:
            last_heartbeat = row['last_controller_heartbeat']
            device_id = row['id']

            if last_heartbeat:
                # Convert PostgreSQL datetime to epoch seconds
                time_diff = current_time - int(last_heartbeat.timestamp())

                if time_diff > THRESHOLD_SECONDS:
                    try:
                        subject = "Device Heartbeat Alert"
                        body = (
                            f"Hello,\n\n"
                            f"The device with ID `{device_id}` has not sent a heartbeat for the past {time_diff} seconds "
                            f"(Last seen at: {last_heartbeat}).\n\n"
                            f"Please check the device.\n\n"
                            f"Regards,\nSystem Monitor"
                        )

                        # Send email via SES
                        response = ses_client.send_email(
                            Source=SENDER_EMAIL,
                            Destination={"ToAddresses": RECIPIENT_EMAILS},
                            Message={
                                "Subject": {"Data": subject},
                                "Body": {
                                    "Text": {"Data": body}
                                }
                            }
                        )
                        print(f"Email alert sent for device {device_id}")

                    except Exception as e:
                             return _error_response(404, "heartbeat monitoring failed.")
            return _success_response(200, {"message": "successfully monitored devices.", "device": device_id})
                           