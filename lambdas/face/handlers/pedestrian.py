import boto3
import base64
from datetime import datetime
from utils import _error_response, _success_response, log, notify_user
from middleware import verify_token
from psycopg2.extras import RealDictCursor

rekognition = boto3.client('rekognition')
s3 = boto3.client('s3')

bucket_name = 'itc-lpr-bucket'


def detect_face(image):
    try:
        response = rekognition.detect_faces(  
            Image={'Bytes': image},  # Pass the image bytes using the 'Bytes' keyword
            Attributes=['ALL'])
        print(f"Rekognition response: {response}")
        return response
    except Exception as e:
        print(f"Error analyzing image with Rekognition: {e}")
        return None

def upload_image_to_s3(image, object_name, metadata=None):
    try:
        s3.put_object(Bucket=bucket_name, Key=object_name, Body=image, Metadata=metadata)
        # object_key = f"gate-app-faces/{object_name}"
        print(f"Image uploaded to S3 bucket '{bucket_name}' with object name '{object_name}'.")
    except Exception as e:
        print(f"Error uploading image to S3: {e}")
        return False
    return True

def upload_vehicle_image_to_s3(body, event):
    payload, error = verify_token(event)
    if error:
        return error
    
    image = body["image"]
    file_name = body["file_name"]
    image_bytes = base64.b64decode(image)
    object_name = f'lpr-images/{file_name}'
    metadata = {'key': body["key"]}
    
    payload, error = verify_token(event)
    if error:
        return error
    
    try:
        s3.put_object(Bucket=bucket_name, Key=object_name, Body=image_bytes, Metadata=metadata)
        # object_key = f"gate-app-faces/{object_name}"
        print(f"Image uploaded to S3 bucket '{bucket_name}' with object name '{object_name}'.")
    except Exception as e:
        print(f"Error uploading image to S3: {e}")
        return False
    return True

def index_face(image):

    response = rekognition.index_faces(
        Image={'Bytes': image},
        CollectionId='gate_app_collection_id' 
    )
    if response['FaceRecords']:
            # Extract Face ID from the first detected face
            face_id = response['FaceRecords'][0]['Face']['FaceId']
            print(f"Face ID: {face_id}")
            return face_id
    else:
        print("No faces were detected in the image.")
        return None

def delete_image_from_collection(face_id):
    try:
        response = rekognition.delete_faces(
            CollectionId = 'gate_app_collection_id',
            FaceIds = [face_id]
        )
        print(f"Deleted face ID(s): {response['DeletedFaces']}")
    except Exception as e:
        print(f"Error deleting image: {e}")

def match_guest_face(conn, body, event):
    """
    Looks up matching faces in a Rekognition collection, checks if any match
    is found in our local 'faces' table, and if so, deletes that face from the DB
    and Rekognition.
    """
    payload, error = verify_token(event)
    if error:
        return error

    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "TABLET"):
        return _error_response(401, "Unauthorized.")
    
    image = body.get('image')
    image_bytes = base64.b64decode(image)

    try:
        response = rekognition.search_faces_by_image(
            CollectionId='gate_app_collection_id',
            Image={'Bytes': image_bytes}
        )

        face_matches = response.get('FaceMatches', [])
        if not face_matches:
            print("No faces matched in Rekognition.")
            return None  # or return a specific message

        face_id_to_delete = None

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for match in face_matches:
                face_id = match['Face']['FaceId']
                confidence = match['Face']['Confidence']
                print(f"Rekognition match: FaceId={face_id}, Confidence={confidence}")

                # Correctly pass parameters as a tuple
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM faces
                        WHERE faces.id = %s
                    ) AS face_exists
                """, (face_id,))

                if cur.fetchone()["face_exists"]:
                    # We found a matching face in our DB
                    face_id_to_delete = face_id
                    break  # Stop looking for other matches

            if not face_id_to_delete:
                # No matching face found in local DB
                _error_response(404, "Face not found in DB.")

            # Delete the face from our 'faces' table
            cur.execute(
            """
                UPDATE guests
                SET status = 'CHECKED_OUT'
                WHERE id = (SELECT guest_id FROM faces WHERE id = %s)
                RETURNING id
            """,
            (face_id_to_delete,)
            )

            updated_guest = cur.fetchone()
            if not updated_guest:
                return _error_response(400, "Guest does not exist or could not be updated.")
        
            cur.execute("""
                DELETE FROM faces
                WHERE id = %s
                RETURNING id
            """, (face_id_to_delete,))

            row = cur.fetchone()
            if not row:
                # Means the face was not actually in DB or was already deleted
                return _error_response(404, "Face not found in DB.")
            
            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            gate_data = cur.fetchone()

            cur.execute("""
                SELECT ah.user_id, g.name FROM guests g
                JOIN account_holders ah ON ah.id = g.creator_id
                WHERE g.id = %s
            """, (updated_guest["id"],))

            g = cur.fetchone()

            notify_user(g["user_id"], "Guest Arrival", f"{g['name']} has exited")
            
            log(conn, "FACE_MATCH", f"Face matched. Guest exited at gate '{gate_id}' [{gate_data['name']}]", None, None, gate_data["estate_id"])
            
            conn.commit()

        # Also remove it from the Rekognition collection
        delete_image_from_collection(face_id_to_delete)
        return _success_response(200, {"message": "Match successful."})

    except Exception as e:
        return _error_response(500, f"An error occured: {e}")
    
def save_guest_face(conn, body, event):
    """
    Registers a new vehicle under a personal_info entry.
    """
    payload, error = verify_token(event)
    if error:
        return error
    
    gate_id = payload.get("gate_id", None)
    device_type = payload.get("type", None)

    if not (gate_id and device_type == "TABLET"):
        return _error_response(401, "Unauthorized.")

    inviter_user_id = body.get("inviter_user_id")
    guest_name = body.get("guest_name")
    guest_id = body.get("guest_id")
    image = body.get("image")

    if not all([inviter_user_id, guest_id, guest_name, image]):
        return _error_response(400, "Missing required fields. 'inviter_user_id', 'guest_id', 'guest_name', 'image'")
    
    image_bytes = base64.b64decode(image)
    rekognition_response = detect_face(image_bytes)

    # if rekognition_response is not None and rekognition_response['FaceDetails']:
    if rekognition_response.get('FaceDetails', None):
        face_id = index_face(image_bytes)
        object_name = f'gate-app-faces/{face_id}.jpg'
        metadata = {'name': guest_name}
        upload_image_to_s3(image_bytes, object_name, metadata)
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            
            cur.execute("""
                        INSERT INTO faces (id, guest_id)
                        VALUES (%s, %s)
                        RETURNING id 
                        """, (face_id, guest_id))   

            cur.execute(
                """
                    UPDATE guests
                    SET status = 'CHECKED_IN'
                    WHERE id = (SELECT guest_id FROM faces WHERE id = %s)
                    RETURNING id
                """,
            (face_id,)
            )

            updated_guest = cur.fetchone()
            if not updated_guest:
                return _error_response(400, "Guest does not exist or could not be updated.")   

            cur.execute("""
                SELECT estate_id, name FROM gates g
                WHERE g.id = %s
            """, (gate_id,))

            gate_data = cur.fetchone()
            
            cur.execute("""
                SELECT ah.user_id FROM guests g
                JOIN account_holders ah ON ah.id = g.creator_id
                WHERE g.id = %s
            """, (guest_id,))

            g = cur.fetchone()

            notify_user(g["user_id"], "Guest Arrival", f"{g['name']} has arrived")

            log(conn, "FACE_SAVED", f"Face saved. Guest entered at gate '{gate_id}' [{gate_data['name']}]", None, None, gate_data["estate_id"])      

            conn.commit()

    return _success_response(201, {"message": "Face saved successfully."})
