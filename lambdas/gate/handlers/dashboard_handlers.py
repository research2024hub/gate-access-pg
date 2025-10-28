from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor
from utils import _error_response, _success_response, log  # project-level helpers
from middleware import verify_token

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
        return _error_response(403, "gate_mismatch", "gate_id in body does not match token")

    gate_id = token_gate_id  # trust token value
    if not timestamp_str or gate_id is None:
        return _error_response(
            400,
            "missing_fields",
            "'timestamp' and 'gate_id' are required fields in the request body.",
        )

    # Convert timestamp to datetime (server-side UTC for storage)
    try:
        device_ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")) if timestamp_str else None
    except ValueError:
        return _error_response(400, "invalid_timestamp", "timestamp must be ISO-8601 ISO 8601 string.")

    if device_ts is None:
        return _error_response(400, "missing_timestamp", "'timestamp' field is required")

    # Optional numeric validation
    temperature = body.get("temperature_celsius")

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
                    json.dumps(body.get("running_services")),
                    body.get("storage_used_gb"),
                    body.get("storage_total_gb"),
                    json.dumps(body.get("offline_camera_ids")),
                ),
            )
            metric_id = cur.fetchone()["id"]
            conn.commit()
    except Exception as exc:
        print("Failed to save system metrics: %s", exc)
        conn.rollback()
        return _error_response(500, "db_error", "Could not store metrics.")
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
        return _error_response(400, "missing_gate_id", "gate_id is required")
    try:
        gate_id_int = int(gate_id)
    except ValueError:
        return _error_response(400, "invalid_gate_id", "gate_id must be integer")

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
            return _error_response(404, "not_found", "No metrics found for this gate")

    running_services = json.loads(row["running_services"]) if row.get("running_services") else []
    row["number_running_services"] = len(running_services)
    row["total_number_services"] = row.get("total_cameras")

    return _success_response(200, {
        "data_received_at": row["received_at"].isoformat(),
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
        return _error_response(400, "missing_params", "start_date and end_date are required")
    try:
        start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_dt   = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return _error_response(400, "invalid_date", "Dates must be ISO8601")

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
        trend.append({"timestamp": ts_iso, "temperature_celsius": sum(vals)/len(vals)})

    return _success_response(200, {"trend_data": trend})


# ----------------------------------------------------------------------------
# 4.4 GET /cameras/downtime – get_camera_downtime
# ----------------------------------------------------------------------------

def get_camera_downtime(conn, event):
    """Returns list of camera downtime periods between start_date & end_date.

    This naïve implementation infers downtime when a camera ID appears in
    `offline_camera_ids` for consecutive records. Production logic should be
    replaced with a more robust algorithm and permanent storage.
    """
    query = event.get("queryStringParameters") or {}
    start_date_str = query.get("start_date")
    end_date_str = query.get("end_date")
    if not (start_date_str and end_date_str):
        return _error_response(400, "missing_params", "start_date and end_date are required query parameters")

    try:
        start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
    except ValueError as exc:
        return _error_response(400, "invalid_date", "Dates must be ISO-8601", str(exc))

    gate_id = query.get("gate_id")

    sql = "SELECT device_timestamp, offline_camera_ids FROM system_metrics WHERE device_timestamp BETWEEN %s AND %s"
    params = [start_dt, end_dt]
    if gate_id:
        sql += " AND gate_id = %s"
        params.append(gate_id)
    sql += " ORDER BY device_timestamp ASC"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        records = cur.fetchall()

    downtime_events: List[Dict[str, Any]] = []
    ongoing: Dict[str, datetime] = {}

    for rec in records:
        rec_ts = datetime.fromisoformat(rec["metrics"]["timestamp"].replace("Z", "+00:00"))
        if not (start_dt <= rec_ts <= end_dt):
            continue

        if gate_id and str(rec["metrics"].get("gate_id")) != gate_id:
            continue

        offline_cameras = set(rec["metrics"].get("offline_camera_ids") or [])

        # Detect newly offline cameras.
        for cam in offline_cameras:
            if cam not in ongoing:
                ongoing[cam] = rec_ts  # start downtime

        # Detect cameras that came back online.
        cams_now_online = [cam for cam in list(ongoing) if cam not in offline_cameras]
        for cam in cams_now_online:
            start_time = ongoing.pop(cam)
            downtime_events.append(
                {
                    "camera_id": cam,
                    "start_time": start_time.isoformat().replace("+00:00", "Z"),
                    "end_time": rec_ts.isoformat().replace("+00:00", "Z"),
                    "duration_minutes": int((rec_ts - start_time).total_seconds() / 60),
                }
            )

    # Any cameras still offline at end_date -> open downtime events.
    for cam, start_time in ongoing.items():
        downtime_events.append(
            {
                "camera_id": cam,
                "start_time": start_time.isoformat().replace("+00:00", "Z"),
                "end_time": None,
                "duration_minutes": None,
            }
        )

    response_body = {"downtime_history": downtime_events}
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response_body),
    }


# ----------------------------------------------------------------------------
# Convenience: mapping of routes to handlers (optional for frameworks)
# ----------------------------------------------------------------------------
ROUTE_TABLE = {
    "POST /system/metrics": ingest_system_metrics,
    "GET /system/metrics/latest": get_latest_system_metrics,
    "GET /system/metrics/temperature/trend": get_temperature_trend,
    "GET /cameras/downtime": get_camera_downtime,
}

"""You can use ROUTE_TABLE to dispatch based on the HTTP method + path when
wiring up in a minimal custom Lambda handler or another framework."""
