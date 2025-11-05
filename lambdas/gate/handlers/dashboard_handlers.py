from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor
from utils import _error_response as _base_error_response, _success_response as _base_success_response, log  # project-level helpers
from middleware import verify_token, cors_wrap

# ---------------------------------------------------------------------------
# CORS helper & patched response wrappers
# ---------------------------------------------------------------------------
# CORS_HEADERS = {
#     "Access-Control-Allow-Origin": "*",  # TODO: restrict to specific domain if needed
#     "Access-Control-Allow-Headers": "Content-Type,Authorization",
#     "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE",
#     "Access-Control-Max-Age": "86400",  # 24h
# }

# def _cors_wrap(resp: dict) -> dict:
#     """Inject CORS headers into a Lambda proxy response dict."""
#     hdrs = resp.get("headers", {}) or {}
#     hdrs.update(CORS_HEADERS)
#     resp["headers"] = hdrs
#     return resp

# Override the project-level helpers so that *every* successful or error
# response produced inside this module automatically includes CORS headers.

def _success_response(status_code: int, body: dict):
    return cors_wrap(_base_success_response(status_code, body))

def _error_response(status_code: int, message: str):
    return cors_wrap(_base_error_response(status_code, message))

# logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO)

# ----------------------------------------------------------------------------
# Temporary in-memory store (to be removed once all endpoints use PostgreSQL)
# ----------------------------------------------------------------------------
_METRICS_DATA: List[Dict[str, Any]] = []

# ----------------------------------------------------------------------------
# 4.1 POST /system/metrics – ingest_system_metrics
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4.1  POST /system/metrics  –  ingest_system_metrics
# ---------------------------------------------------------------------------

def ingest_system_metrics(conn, body, event):
    payload, error = verify_token(event)
    if error:
        return error

    # Gate controllers include `gate_id` + `type: GATE` in the token
    token_gate_id = payload.get("gate_id")
    device_type   = payload.get("type")

    if not (token_gate_id and device_type == "GATE"):
        return _error_response(401, "Unauthorized")

    # ---------------------------------------------------------------------
    # 2.  Validate request body (already parsed by caller -> `body` argument)
    # ---------------------------------------------------------------------
    timestamp_str = body.get("timestamp")
    gate_id       = body.get("gate_id")

    if gate_id and gate_id != token_gate_id:
        # Device should only send metrics for its own gate_id
        return _error_response(403, "gate_mismatch: gate_id in body does not match token")

    gate_id = token_gate_id  # trust token value
    if not timestamp_str or gate_id is None:
        return _error_response(
            400,
            "missing_fields: 'timestamp' and 'gate_id' are required fields in the request body."
        )

    # Convert timestamp to datetime (server-side UTC for storage)
    try:
        device_ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")) if timestamp_str else None
    except ValueError:
        return _error_response(400, "invalid_timestamp: timestamp must be ISO-8601 ISO 8601 string.")

    if device_ts is None:
        return _error_response(400, "missing_timestamp: 'timestamp' field is required")

    # ---------------------------------------------------------------------
    # Validate presence of all metrics that are NOT NULL in the DB schema
    # ---------------------------------------------------------------------
    required_numeric_fields = [
        "temperature_celsius",
        "total_cameras",
        "online_cameras",
        "storage_used_gb",
        "storage_total_gb",
    ]
    missing_fields = [f for f in required_numeric_fields if body.get(f) is None]
    if missing_fields:
        return _error_response(
            400,
            f"missing_fields: {', '.join(missing_fields)} must be provided and non\u2011null.",
        )

    # ---------------------------------------------------------------------
    # 3.  Persist into DB (table: system_metrics).  If the table is missing
    #     migration, the handler will still succeed but log a warning.
    # ---------------------------------------------------------------------
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO system_metrics (
                    gate_id,
                    device_timestamp,
                    temperature_celsius,
                    total_cameras,
                    online_cameras,
                    running_services,
                    storage_used_gb,
                    storage_total_gb,
                    offline_camera_ids,
                    received_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (
                    gate_id,
                    device_ts,
                    body.get("temperature_celsius"),
                    body.get("total_cameras"),
                    body.get("online_cameras"),
                    json.dumps(body.get("running_services") or {}),
                    body.get("storage_used_gb"),
                    body.get("storage_total_gb"),
                    json.dumps(body.get("offline_camera_ids") or []),
                ),
            )
            metric_id = cur.fetchone()["id"]
            conn.commit()
    except Exception as exc:
        print("Failed to save system metrics: %s", exc)
        conn.rollback()
        return _error_response(500, "db_error: Could not store metrics.")
    _METRICS_DATA.append({
        "data_received_at": datetime.now(timezone.utc),
        "metrics": body,
    })
    print("Stored system metrics id=%s for gate_id=%s", metric_id, gate_id)

    return _success_response(201, {"message": "Metrics received successfully", "metric_id": metric_id})


# ----------------------------------------------------------------------------
# 4.2 GET /system/metrics/latest – get_latest_system_metrics
# ----------------------------------------------------------------------------

def get_latest_system_metrics(conn, event):
    """Return latest stored metrics row from DB.

    If the caller is a gate controller it can omit ?gate_id – the value from
    its token will be used. Admin callers must provide ?gate_id.
    """
    payload, error = verify_token(event)
    if error:
        return error

    query_params = event.get("queryStringParameters") or {}
    gate_id = query_params.get("gate_id") or payload.get("gate_id")
    if not gate_id:
        return _error_response(400, "missing_gate_id: gate_id is required")
    try:
        gate_id_int = int(gate_id)
    except ValueError:
        return _error_response(400, "invalid_gate_id: gate_id must be integer")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT *
            FROM system_metrics
            WHERE gate_id = %s
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (gate_id_int,),
        )
        row = cur.fetchone()
        if not row:
            return _error_response(404, "not_found: No metrics found for this gate")

    # Parse `running_services`, which may already be a decoded Python object
    rs_raw = row.get("running_services")
    if rs_raw in (None, ""):
        running_services = []
    elif isinstance(rs_raw, (list, dict)):
        running_services = rs_raw
    else:
        try:
            running_services = json.loads(rs_raw)
        except Exception:
            running_services = []  # Fallback if JSON cannot be parsed
    row["running_services"] = running_services
    row["number_running_services"] = len(running_services)
    row["total_number_services"] = row.get("total_cameras")
    # Recursively convert any datetime objects (including nested ones) to ISO-8601 strings
    def _convert_dt(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            # Convert decimals to plain floats for JSON serialisation
            return float(obj)
        if isinstance(obj, list):
            return [_convert_dt(v) for v in obj]
        if isinstance(obj, dict):
            return {k: _convert_dt(v) for k, v in obj.items()}
        return obj

    row = _convert_dt(row)

    return _success_response(200, {
        "data_received_at": row["received_at"] if isinstance(row["received_at"], str) else row["received_at"].isoformat(),
        "metrics": row,
    })


# ----------------------------------------------------------------------------
# 4.3 GET /system/metrics/temperature/trend – get_temperature_trend
# ----------------------------------------------------------------------------

def get_temperature_trend(conn, event):
    """Returns historical temperature data within the requested window.

    Required query params: start_date, end_date (ISO-8601).
    Optional: device_id, granularity (hourly|daily|raw).
    """
    query = event.get("queryStringParameters") or {}
    start_date = query.get("start_date")
    end_date   = query.get("end_date")
    if not (start_date and end_date):
        return _error_response(400, "missing_params: start_date and end_date are required")
    try:
        start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_dt   = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return _error_response(400, "invalid_date: Dates must be ISO8601")

    gate_id = query.get("gate_id")
    granularity = (query.get("granularity") or "auto").lower()

    sql = "SELECT device_timestamp, temperature_celsius FROM system_metrics WHERE device_timestamp BETWEEN %s AND %s"
    params = [start_dt, end_dt]
    if gate_id:
        sql += " AND gate_id = %s"
        params.append(gate_id)
    sql += " ORDER BY device_timestamp ASC"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        return _success_response(200, {"trend_data": []})

    buckets: Dict[Any, List[float]] = {}
    def bucket_key(ts: datetime):
        if granularity == "hourly":
            return ts.replace(minute=0, second=0, microsecond=0)
        elif granularity == "daily":
            return ts.date()
        return ts

    for r in rows:
        buckets.setdefault(bucket_key(r["device_timestamp"]), []).append(r["temperature_celsius"])

    trend = []
    for key, vals in sorted(buckets.items()):
        ts_iso = key.isoformat() if isinstance(key, datetime) else datetime(key.year, key.month, key.day, tzinfo=timezone.utc).isoformat()
        avg_temp = sum(vals)/len(vals)
        trend.append({"timestamp": ts_iso, "temperature_celsius": float(avg_temp)})

    return _success_response(200, {"trend_data": trend})


# ----------------------------------------------------------------------------
# 4.4 GET /system/metrics/storage/trend – get_storage_trend
# ----------------------------------------------------------------------------

def get_storage_trend(conn, event):
    """Returns historical storage usage data within the requested window.

    Required query params: start_date, end_date (ISO-8601).
    Optional: gate_id, granularity (hourly|daily|raw).
    """
    query = event.get("queryStringParameters") or {}
    start_date = query.get("start_date")
    end_date = query.get("end_date")
    if not (start_date and end_date):
        return _error_response(400, "missing_params: start_date and end_date are required")

    try:
        start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return _error_response(400, "invalid_date: Dates must be ISO8601")

    gate_id = query.get("gate_id")
    granularity = (query.get("granularity") or "auto").lower()

    sql = (
        "SELECT device_timestamp, storage_used_gb, storage_total_gb "
        "FROM system_metrics WHERE device_timestamp BETWEEN %s AND %s"
    )
    params = [start_dt, end_dt]
    if gate_id:
        sql += " AND gate_id = %s"
        params.append(gate_id)
    sql += " ORDER BY device_timestamp ASC"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        return _success_response(200, {"trend_data": []})

    buckets: Dict[Any, List[Dict[str, Decimal]]] = {}

    def bucket_key(ts: datetime):
        if granularity == "hourly":
            return ts.replace(minute=0, second=0, microsecond=0)
        elif granularity == "daily":
            return ts.date()
        return ts

    for r in rows:
        buckets.setdefault(bucket_key(r["device_timestamp"]), []).append(
            {
                "used": r["storage_used_gb"],
                "total": r["storage_total_gb"],
            }
        )

    trend = []
    for key, vals in sorted(buckets.items()):
        ts_iso = (
            key.isoformat()
            if isinstance(key, datetime)
            else datetime(key.year, key.month, key.day, tzinfo=timezone.utc).isoformat()
        )
        avg_used = sum(v["used"] for v in vals) / len(vals)
        avg_total = sum(v["total"] for v in vals) / len(vals)
        used_pct = (avg_used / avg_total * 100) if avg_total else None
        trend.append(
            {
                "timestamp": ts_iso,
                "storage_used_gb": float(avg_used),
                "storage_total_gb": float(avg_total),
                "storage_used_pct": float(used_pct) if used_pct is not None else None,
            }
        )

    return _success_response(200, {"trend_data": trend})


# ----------------------------------------------------------------------------
# 4.5 GET /cameras/downtime – get_camera_downtime
# ----------------------------------------------------------------------------

def get_camera_downtime(conn, event):
    """Return camera downtime history between *start_date* and *end_date*.

    Required query parameters (ISO-8601 strings):
        • gate_id   – integer
        • start_date
        • end_date

    The endpoint analyses the *offline_camera_ids* column to infer periods
    when each camera was offline inside the requested interval.
    """
    query = event.get("queryStringParameters") or {}
    gate_id = query.get("gate_id")
    start_date_str = query.get("start_date")
    end_date_str = query.get("end_date")

    if not (gate_id and start_date_str and end_date_str):
        return _error_response(400, "missing_params: gate_id, start_date and end_date are required")

    try:
        gate_id_int = int(gate_id)
        start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        return _error_response(400, f"invalid_param: {exc}")

    sql = (
        "SELECT device_timestamp, offline_camera_ids "
        "FROM system_metrics "
        "WHERE gate_id = %s AND device_timestamp BETWEEN %s AND %s "
        "ORDER BY device_timestamp ASC"
    )

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (gate_id_int, start_dt, end_dt))
        records = cur.fetchall()

    downtime_events: List[Dict[str, Any]] = []
    ongoing: Dict[str, datetime] = {}

    for rec in records:
        rec_ts = rec["device_timestamp"]
        if isinstance(rec_ts, str):
            rec_ts = datetime.fromisoformat(rec_ts.replace("Z", "+00:00"))
        if rec_ts.tzinfo is None:
            rec_ts = rec_ts.replace(tzinfo=timezone.utc)

        oci_raw = rec.get("offline_camera_ids")
        if oci_raw in (None, ""):
            offline_cameras = set()
        elif isinstance(oci_raw, list):
            offline_cameras = set(oci_raw)
        else:
            try:
                offline_cameras = set(json.loads(oci_raw))
            except Exception:
                offline_cameras = set()

        newly_offline = offline_cameras - ongoing.keys()
        for cam in newly_offline:
            ongoing[cam] = rec_ts

        came_offline = [cam for cam in list(ongoing) if cam not in offline_cameras]
        for cam in came_offline:
            start_time = ongoing.pop(cam)
            downtime_events.append({
                "camera_id": cam,
                "start_time": start_time.isoformat().replace("+00:00", "Z"),
                "end_time": rec_ts.isoformat().replace("+00:00", "Z"),
                "duration_minutes": int((rec_ts - start_time).total_seconds() / 60),
            })

    for cam, start_time in ongoing.items():
        downtime_events.append({
            "camera_id": cam,
            "start_time": start_time.isoformat().replace("+00:00", "Z"),
            "end_time": None,
            "duration_minutes": None,
        })

    return _success_response(200, {"downtime_history": downtime_events})

# ----------------------------------------------------------------------------
# Convenience: mapping of routes to handlers (optional for frameworks)
# ----------------------------------------------------------------------------
# ROUTE_TABLE = {
#     "POST /system/metrics": ingest_system_metrics,
#     "GET /system/metrics/latest": get_latest_system_metrics,
#     "GET /system/metrics/temperature/trend": get_temperature_trend,
#     "GET /system/metrics/storage/trend": get_storage_trend,
#     "GET /cameras/downtime": get_camera_downtime,
# }

"""You can use ROUTE_TABLE to dispatch based on the HTTP method + path when
wiring up in a minimal custom Lambda handler or another framework."""
