import json
from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, process_db_results, log, send_gmail
from middleware import verify_token
import time
import boto3
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from typing import Dict
# ses_client = boto3.client('ses')
SENDER_EMAIL =   "itcresearch85@gmail.com"
RECIPIENT_EMAILS = "itcresearch340@gmail.com"
THRESHOLD_SECONDS = 900  # Adjust based on your requirements
ALERT_COOLDOWN = 86400  # 24 hours in seconds

def send_email_gmail(subject,message):
    # gmail_user = 'vdowana@itconsortiumgh.com'  # e.g. "yourname@gmail.com"
    gmail_app_password = 'acfyapfeypeguwqj'  # the 16-char app password
    # to_email = "jnagai@itconsortiumgh.com"
    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAILS

    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(SENDER_EMAIL, gmail_app_password)
    server.send_message(msg)
    server.quit()


# import time

# def monitor_heartbeat(conn):
#     print("started")
#     try:
#         # Query all heartbeat records
#         with conn.cursor(cursor_factory=RealDictCursor) as cur:
#             cur.execute("SELECT id, last_controller_heartbeat FROM gates")
#             rows = cur.fetchall()
            
#             # REMOVED: print(row) -> row is not defined yet
            
#             current_time = int(time.time())
#             print(f"Current time: {current_time}")

#             for row in rows:
#                 # Ensure your cursor returns a dict, otherwise use row[0] and row[1]
#                 last_heartbeat = row['last_controller_heartbeat']
#                 device_id = row['id']
                
#                 print("Checking device id:", device_id)
                
#                 if last_heartbeat:
#                     # Convert PostgreSQL datetime to epoch seconds
#                     time_diff = current_time - int(last_heartbeat.timestamp())
#                     print(f"Time difference is {time_diff}")
                    
#                     if time_diff > THRESHOLD_SECONDS:
#                         try:
#                             subject = "Device Heartbeat Alert"
#                             body = (
#                                 f"Hello,\n\n"
#                                 f"The device with ID `{device_id}` has not sent a heartbeat for the past {time_diff} seconds "
#                                 f"(Last seen at: {last_heartbeat}).\n\n"
#                                 f"Please check the device.\n\n"
#                                 f"Regards,\nSystem Monitor"
#                             )
                            
#                             send_email_gmail(subject, body)
#                             print(f"Email alert sent for device {device_id}")

#                         except Exception as e:
#                             print(f"Failed to send email for device {device_id}: {e}")
#                             # CHANGED: Do not return here. Just log and continue to next device.
#                             continue 
            
#         # CHANGED: Dedented this to run AFTER the loop finishes
#         # FIXED: Added missing '}'
#         return _success_response(200, {"message": "successfully monitored devices"})

#     except Exception as e:
#         # Catch database connectivity errors
#         print(f"Database error: {e}")
#         return _error_response(500, "Monitoring execution failed.")


def format_downtime(seconds):
    seconds = int(seconds)
    intervals = (
        ('day', 86400),    # 60 * 60 * 24
        ('hour', 3600),    # 60 * 60
        ('minute', 60),
        ('second', 1),
    )

    result = []
    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            result.append(f"{value} {name}{'s' if value > 1 else ''}")
    
    return ", ".join(result[:2])  # Return only the two biggest units

# def monitor_heartbeat(conn):
#     print("started")
#     try:
#         # Pass the factory here so 'rows' become dictionaries
#         with conn.cursor(cursor_factory=RealDictCursor) as cur:
            
#             # Query the necessary columns
#             cur.execute("""
#               SELECT 
#                     g.id, 
#                     g.last_controller_heartbeat, 
#                     g.last_alert_sent_at,
#                     g.name,
#                     u.email
#                 FROM gates g
#                 LEFT JOIN personal_info pi ON g.estate_id = pi.estate_id
#                 LEFT JOIN account_holders a ON pi.id = a.personal_info_id
#                 LEFT JOIN users u ON a.user_id = u.id  
#             """)
            
#             rows = cur.fetchall()
            
#             current_time = int(time.time())

#             for row in rows:
#                 # NOW you can use column names!
#                 device_id = row['id']
#                 last_heartbeat = row['last_controller_heartbeat']
#                 last_alert = row['last_alert_sent_at']
#                 email = row['email']
#                 name = row['name']
#                 print(f"Checking device: {device_id}")

#                 if last_heartbeat:
#                     last_seen_seconds = int(last_heartbeat.timestamp())
#                     down_time = current_time - last_seen_seconds
                    
#                     # 1. Check if device is legally "down"
#                     if down_time > THRESHOLD_SECONDS:
#                         down_timer = format_downtime(down_time)
#                         # 2. Check if we are allowed to email (Smart Alert Logic)
#                         should_alert = False
                        
#                         if last_alert is None:
#                             # Never alerted before
#                             should_alert = True
#                             print("  Status: First time alert.")
#                         else:
#                             # Alerted before, check if 24 hours passed
#                             last_alert_seconds = int(last_alert.timestamp())
#                             time_since_alert = current_time - last_alert_seconds
                            
#                             if time_since_alert > ALERT_COOLDOWN:
#                                 should_alert = True
#                                 print(f"  Status: Cooldown expired ({time_since_alert}s). Resending.")
#                             else:
#                                 print(f"  Status: In cooldown. Skipping.")

#                         # 3. Execute Alert
#                         if should_alert:
#                             try:
#                                 # Format: YYYY-MM-DD HH:MM:SS.ss
#                                 readable_timestamp = last_heartbeat.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]
#                                 subject = "Device Heartbeat Alert"
#                                 body = (
#                                     f"Hello,\n\n"
#                                     f"The device with ID {device_id} is down.\n"
#                                     f"Down for: {down_timer}\n"
#                                     f"Last seen: {readable_timestamp}.\n\n"
#                                     f"Regards,\nSystem Monitor"
#                                 )

#                                 send_email_gmail(subject, body)
#                                 message = f"We are currently experiencing technical difficulties with the {name} . Our team is investigating the issue and working on a fix right now. We apologize for the interruption and expect to be back online shortly."
#                                 topic = "Gate Access System Update"
#                                 send_gmail(email,topic, message)
#                                 print(f"  >> Email sent for {device_id}")
                                
#                                 # Update DB to prevent spamming
#                                 cur.execute(
#                                     "UPDATE gates SET last_alert_sent_at = NOW() WHERE id = %s", 
#                                     (device_id,)
#                                 )
#                                 conn.commit() # Save the timestamp!

#                             except Exception as e:
#                                 print(f"  !! Failed to send email/update DB: {e}")
#                                 continue
            
#             # This is now correctly indented outside the loop but inside the 'try'
#             return _success_response(200, {"message": "successfully monitored devices"})

#     except Exception as e:
#         print(f"Critical Monitoring Error: {e}")
#         return _error_response(500, "Monitoring execution failed.")

def monitor_heartbeat(conn):
    print("started")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            
            # --- FIXED SQL QUERY ---
            # 1. We use GROUP BY so we get exactly ONE row per device (Gate).
            # 2. We use 'array_agg' to combine all user emails for that gate into a list.
            cur.execute("""
              SELECT 
                    g.id, 
                    g.last_controller_heartbeat, 
                    g.last_alert_sent_at,
                    g.name,
                    array_agg(u.email) FILTER (WHERE u.email IS NOT NULL) AS user_emails
                FROM gates g
                LEFT JOIN personal_info pi ON g.estate_id = pi.estate_id
                LEFT JOIN account_holders a ON pi.id = a.personal_info_id
                LEFT JOIN users u ON a.user_id = u.id  
                GROUP BY g.id, g.last_controller_heartbeat, g.last_alert_sent_at, g.name
            """)
            
            rows = cur.fetchall()
            print("the data",rows)
            current_time = int(time.time())

            for row in rows:
                device_id = row['id']
                last_heartbeat = row['last_controller_heartbeat']
                print("last alert at",last_heartbeat)
                last_alert = row['last_alert_sent_at']
                print("last alert at",last_alert)
                name = row['name']
                # This is now a LIST of emails: ['user1@gmail.com', 'user2@yahoo.com']
                user_emails_list = row['user_emails']

                print(f"Checking device: {device_id}")

                if last_heartbeat:
                    last_seen_seconds = int(last_heartbeat.timestamp())
                    print("last seen",last_seen_seconds)
                    down_time = current_time - last_seen_seconds
                    
                    if down_time > THRESHOLD_SECONDS:
                        down_timer = format_downtime(down_time)
                        should_alert = False
                        
                        if last_alert is None:
                            should_alert = True
                            print("  Status: First time alert.")
                        else:
                            last_alert_seconds = int(last_alert.timestamp())
                            time_since_alert = current_time - last_alert_seconds
                            print(time_since_alert)
                            
                            if time_since_alert > ALERT_COOLDOWN:
                                should_alert = True
                                print(f"  Status: Cooldown expired. Resending.")
                            else:
                                print(f"  Status: In cooldown. Skipping.")
                        

                        if should_alert:
                            try:
                                readable_timestamp = last_heartbeat.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]
                                cur.execute(
                                    "UPDATE gates SET last_alert_sent_at = NOW() WHERE id = %s", 
                                    (device_id,)
                                )
                                conn.commit()
                                # --- 1. ADMIN ALERT (Fixes your issue) ---
                                # This now runs exactly ONCE per device, because the loop runs once per device.
                                subject = "Device Heartbeat Alert"
                                admin_body = (
                                    f"Hello,\n\n"
                                    f"The device with ID {device_id} is down.\n"
                                    f"Down for: {down_timer}\n"
                                    f"Last seen: {readable_timestamp}.\n\n"
                                    f"Regards,\nSystem Monitor"
                                )
                                # Sends ONE email to the admin
                                send_email_gmail(subject, admin_body)
                                print(f"  >> Admin Alert sent for {device_id}")

                                # --- 2. USER ALERTS (Preserves original behavior) ---
                                # We now loop through the list of emails to ensure every user still gets their notification.
                                user_message =(f"We are currently experiencing technical difficulties with the {name} . Our team is investigating the issue and working on a fix right now. We apologize for the interruption and expect to be back online shortly.\n\n"
                                                f"Regards,\nSystem Monitor")
                                
                                user_topic = "Gate Access System Update"
                                
                                # for email in user_emails_list:
                                #     if email: # Safety check to skip empty emails
                                #         send_gmail(email, user_topic, user_message)

                                # --- 3. UPDATE DB ---
                                
                             

                            except Exception as e:
                                print(f"  !! Failed to send email/update DB: {e}")
                                continue
            
            return _success_response(200, {"message": "successfully monitored devices"})

    except Exception as e:
        print(f"Critical Monitoring Error: {e}")
        return _error_response(500, "Monitoring execution failed.")
# -------------------------
# Main function
# -------------------------
def get_camera_downtime(conn):
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(minutes=15)

    sql = """
        SELECT device_timestamp, offline_camera_ids, camera_alert_ts, gate_id
        FROM system_metrics
        WHERE device_timestamp >= %s
        ORDER BY device_timestamp ASC
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (start_dt))
        records = cur.fetchall()

    # Track ongoing offline cameras
    ongoing: Dict[str, datetime] = {}
    alerted_this_run: set[str] = set()

    for rec in records:
        # -------------------------
        # Timestamp processing
        # -------------------------
        ts = rec["device_timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # -------------------------
        # Current offline cameras
        # -------------------------
        raw = rec.get("offline_camera_ids")
        gate_id = rec.get('gate_id')
        if not raw:
            offline_now = set()
        elif isinstance(raw, list):
            offline_now = set(map(str, raw))
        else:
            try:
                offline_now = set(map(str, json.loads(raw)))
            except Exception:
                offline_now = set()

        # -------------------------
        # Last alert timestamps (JSON)
        # -------------------------
        raw_alert_ts = rec.get("camera_alert_ts")
        try:
            alert_ts_dict = json.loads(raw_alert_ts) if raw_alert_ts else {}
        except Exception:
            alert_ts_dict = {}

        # -------------------------
        # Track new offline cameras
        # -------------------------
        for cam in offline_now:
            if cam not in ongoing:
                ongoing[cam] = ts

        # -------------------------
        # Remove cameras that came back online
        # -------------------------
        for cam in list(ongoing):
            if cam not in offline_now:
                ongoing.pop(cam, None)

        # -------------------------
        # Check for alerts
        # -------------------------
        for cam, start_time in ongoing.items():
            duration_minutes = (ts - start_time).total_seconds() / 60
            if duration_minutes < 10:
                continue

            if cam in alerted_this_run:
                continue

            # Check last alert timestamp for 24-hour cooldown
            last_alert_iso = alert_ts_dict.get(cam)
            if last_alert_iso:
                last_alert_dt = datetime.fromisoformat(last_alert_iso.replace("Z", "+00:00"))
                if ts - last_alert_dt < timedelta(hours=24):
                    continue

            # -------------------------
            # Send alert
            # -------------------------
            subject = "Camera Alert"
            body = (
                    f"Hello,\n\n"
                    f"The camera with ID {raw} is down.\n"
                    f"Last seen: {ts}.\n\n"
                    f"Regards,\nSystem Monitor"
                        )
            send_email_gmail(subject, body)
            alerted_this_run.add(cam)

            # -------------------------
            # Update system_metrics.camera_alert_ts
            # -------------------------
            alert_ts_dict[cam] = ts.isoformat().replace("+00:00", "Z")
            update_sql = """
                UPDATE system_metrics
                SET camera_alert_ts = %s
                WHERE gate_id = %s AND device_timestamp = %s
            """
            with conn.cursor() as cur2:
                cur2.execute(update_sql, (json.dumps(alert_ts_dict), gate_id, ts))
            conn.commit()

    # -------------------------
    # Return offline cameras for the last 15 min
    # -------------------------
    return _success_response(200, {
        "checked_from": start_dt.isoformat().replace("+00:00", "Z"),
        "checked_to": now.isoformat().replace("+00:00", "Z"),
        "currently_offline": [
            {
                "camera_id": cam,
                "offline_since": start.isoformat().replace("+00:00", "Z"),
                "duration_minutes": int((now - start).total_seconds() / 60),
            }
            for cam, start in ongoing.items()
        ],
    })

                           
                           