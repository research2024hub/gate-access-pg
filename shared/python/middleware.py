import jwt
import os
from utils import _error_response

JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")

def verify_token(event):
    """
    Extracts and verifies JWT from request headers.
    """
    auth_header = event.get("headers", {}).get("Authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, _error_response(401, "Authorization token is missing.")

    token = auth_header.split(" ")[1]

    try:
        print(token)
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        print(payload)
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, _error_response(401, "Token has expired.")
    except jwt.InvalidTokenError:
        return None, _error_response(401, "Invalid token.")
