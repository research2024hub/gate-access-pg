import jwt
import os
from utils import _error_response
from google.oauth2 import id_token
from google.auth.transport import requests
import json
# ---------------------------------------------------------------------------
# JWT verification helper (existing code)
# ---------------------------------------------------------------------------
JWT_SECRET = os.environ["JWT_SECRET"]
GOOGLE_CLIENT_ID_AND = os.environ.get("GOOGLE_CLIENT_ID_AND")
GOOGLE_CLIENT_ID_IOS = os.environ.get("GOOGLE_CLIENT_ID_IOS")
ALLOWED_CLIENT_IDS = [GOOGLE_CLIENT_ID_AND, GOOGLE_CLIENT_ID_IOS]
def verify_token(event, conn=None):
    """
    Extracts and verifies the JWT from request headers.

    If a live DB connection is passed and the token carries a ``user_id``, the
    user is also checked against the database: a soft-deleted or deactivated
    account is rejected even when its (up to 1-year) token is still
    cryptographically valid. Handlers that mutate state or return private data
    should always pass ``conn``.
    """
    auth_header = (event.get("headers") or {}).get("Authorization", (event.get("headers") or {}).get("authorization", ""))
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, cors_wrap(_error_response(401, "Authorization token is missing."))

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, cors_wrap(_error_response(401, "Token has expired."))
    except jwt.InvalidTokenError:
        return None, cors_wrap(_error_response(401, "Invalid token."))

    user_id = payload.get("user_id")
    if conn is not None and user_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM users "
                    "WHERE id = %s AND deleted_at IS NULL AND is_active = TRUE",
                    (user_id,),
                )
                if cur.fetchone() is None:
                    return None, cors_wrap(
                        _error_response(401, "Account is no longer active.")
                    )
        except Exception:
            # Do not authorize a request when account status cannot be verified.
            try:
                conn.rollback()
            except Exception:
                pass
            return None, cors_wrap(_error_response(503, "Unable to verify account status."))

    return payload, None

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
        return cors_wrap(_error_response(500, "Unsuccessful Authentication"))