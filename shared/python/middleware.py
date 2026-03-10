import jwt
import os
from utils import _error_response
from google.oauth2 import id_token
from google.auth.transport import requests
import json
# ---------------------------------------------------------------------------
# JWT verification helper (existing code)
# ---------------------------------------------------------------------------
JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key")
GOOGLE_CLIENT_ID_AND = os.environ.get("GOOGLE_CLIENT_ID_AND")
GOOGLE_CLIENT_ID_IOS = os.environ.get("GOOGLE_CLIENT_ID_IOS")
ALLOWED_CLIENT_IDS = [GOOGLE_CLIENT_ID_AND, GOOGLE_CLIENT_ID_IOS]
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

# ---------------------------------------------------------------------------
# CORS utilities – can be imported by any Lambda handler
# ---------------------------------------------------------------------------
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # TODO: tighten in production
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE",
    "Access-Control-Max-Age": "86400",  # 24 hours
}

def cors_wrap(resp: dict) -> dict:
    """Inject standard CORS headers into a Lambda proxy response dict."""
    hdrs = resp.get("headers", {}) or {}
    hdrs.update(CORS_HEADERS)
    resp["headers"] = hdrs
    return resp


def verify_google_token(token):
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            None
        )
        if idinfo['aud'] not in ALLOWED_CLIENT_IDS:
            raise ValueError("Invalid audience")
        return idinfo

    except ValueError:
        return  _error_response(500, "Unsuccessful Authentication")