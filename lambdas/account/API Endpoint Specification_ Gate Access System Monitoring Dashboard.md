## **API Endpoint Specification: Gate Access System Monitoring Dashboard**

**Version:** 1.0 

**Date:** October 27, 2025 

**1\. Overview**

This document specifies the API endpoints required to support the frontend monitoring dashboard for the Gate Access System (GACS). The dashboard aims to provide administrators with real-time and historical insights into the system's operational status and performance.

**2\. Authentication**

All API endpoints specified below (unless otherwise noted) must be protected and require authentication. The frontend will send a JWT Bearer token in the `Authorization` header with each request after the user has logged in. The authorization can be taken from the administrator login process already developed unless a different type of user is specified for the dashboard usage. 

```
Authorization: Bearer <your_jwt_token>
```

**3\. Data Flow & Responsibilities**

* **Real-time Metrics (Device Push):** Single-value metrics (temperature, camera status, storage, etc.) will be pushed periodically from the on-site controller (e.g., Orange Pi) to a dedicated backend endpoint. The exact interval is TBD but expected to be frequent (e.g., every 1-5 minutes).  
* **Historical Data & Trends (Backend Calculation):** The backend is responsible for storing the incoming real-time metrics and collating/calculating historical trends (temperature) and downtime history based on this stored data.  
* **Dashboard Retrieval (Frontend Pull):** The frontend dashboard will query the backend API endpoints specified below to retrieve both the latest status and historical trend data for display.

**4\. Endpoint Specifications**

**4.1. Ingest System Metrics (Device \-\> Backend)**

This endpoint is for the on-site controller (Orange Pi) to periodically send its current status metrics to the backend for storage.

* **Endpoint:** `POST /system/metrics`  
* **Method:** `POST`  
* **Description:** Receives and stores the latest operational metrics from a specific gate system controller. The controller should ideally identify itself if multiple gate systems might report to the same backend in the future.  
* **Authentication:** The authentication can be the device token that is generated for the controller.   
* **Request Body:**  
  JSON

```
{
  "timestamp": "2025-10-27T08:30:00Z", // ISO 8601 timestamp from the device
  "gate_id": 1, // Unique identifier for the controller sending data
  "temperature_celsius": 45.5,
  "total_cameras": 3,
  "online_cameras": 2,
  "running_services": ["lpr_processor", "gate_controller", "api_reporter"], // List of key service names/IDs running
  "storage_used_gb": 15.2,
  "storage_total_gb": 64.0,
  "offline_camera_ids": ["Camera-3"] // Optional but helpful: Explicit list of offline camera IDs
}
```

*   
* **Success Response:**  
  * **Code:** `201 Created` or `200 OK`  
  * **Body:**  
    JSON

```
{
  "message": "Metrics received successfully for device GATE_01"
}
```

  *   
* **Error Responses:** Standard 4xx/5xx codes with JSON error body (see Section 5).

**4.2. Get Latest System Metrics (Frontend \<- Backend)**

This endpoint provides the dashboard with the most recently received set of metrics for a quick overview.

* **Endpoint:** `GET /system/metrics/latest`  
* **Method:** `GET`  
* **Description:** Retrieves the latest stored metrics record for the system (or a specific device if multi-device support is implemented).  
* **Authentication:** Required (JWT Bearer Token) from the administrator.  
* **Query Parameters (Optional):**  
  * `gate_id` (int): If supporting multiple devices, filter by a specific device.  
* **Success Response:**  
  * **Code:** `200 OK`  
  * **Body:** The structure should mirror the POST request, but include the timestamp when the data was received/stored by the backend.  
    JSON

```
{
  "data_received_at": "2025-10-27T08:30:05Z", // Timestamp when backend stored this
  "metrics": {
    "timestamp": "2025-10-27T08:30:00Z", // Original timestamp from device
    "gate_id": 1,
    "temperature_celsius": 45.5,
    "total_cameras": 3,
    "online_cameras": 2,
    "running_services": ["lpr_processor", "gate_controller", "api_reporter"],
    "number_running_services": 3
    "total_number_services": 3
    "storage_used_gb": 15.2,
    "storage_total_gb": 64.0,
     "offline_camera_ids": ["Camera-3"]
  }
}
```

  *   
  * **Note:** If no metrics have been received yet, return a `200 OK` with an empty or null metrics object, or a `404 Not Found`. Please clarify preferred behaviour.  
* **Error Responses:** Standard 4xx/5xx codes (see Section 5).

**4.3. Get Temperature Trend Data (Frontend \<- Backend)**

This endpoint provides historical temperature data for charting.

* **Endpoint:** `GET /system/metrics/temperature/trend`  
* **Method:** `GET`  
* **Description:** Retrieves a time series of temperature readings within a specified date range. The backend should aggregate/sample data appropriately based on the range requested to avoid returning excessive data points.  
* **Authentication:** Required (JWT Bearer Token).  
* **Query Parameters:**  
  * `start_date` (string, ISO 8601 format, e.g., `2025-10-20T00:00:00Z`): Required. Start of the date range.  
  * `end_date` (string, ISO 8601 format, e.g., `2025-10-27T23:59:59Z`): Required. End of the date range.  
  * `device_id` (string): Optional. Filter by a specific device if supporting multiple.  
  * `granularity` (string): Optional (e.g., `hourly`, `daily`, `raw`). Suggests desired data aggregation level. If omitted, the backend should choose a sensible default based on the date range (e.g., hourly for a day, daily for a month).  
* **Success Response:**  
  * **Code:** `200 OK`  
  * **Body:** An array of timestamp-value pairs.  
    JSON

```
{
  "trend_data": [
    { "timestamp": "2025-10-27T08:00:00Z", "temperature_celsius": 44.8 },
    { "timestamp": "2025-10-27T09:00:00Z", "temperature_celsius": 45.5 },
    // ... more data points based on granularity
  ]
}
```

  *   
* **Error Responses:** Standard 4xx/5xx codes (see Section 5).

**4.4. Get Camera Downtime History (Frontend \<- Backend)**

This endpoint provides a list of periods when cameras were detected as inactive within a specified date range.

* **Endpoint:** `GET /cameras/downtime`  
* **Method:** `GET`  
* **Description:** Retrieves a history of camera downtime events. The backend needs to infer or track when a camera goes offline and comes back online based on the metrics received (e.g., comparing `total_cameras` vs `online_cameras`, or using the `offline_camera_ids` list if provided).  
* **Authentication:** Required (JWT Bearer Token).  
* **Query Parameters:**  
  * `start_date` (string, ISO 8601 format): Required. Start of the date range.  
  * `end_date` (string, ISO 8601 format): Required. End of the date range.  
  * `device_id` (string): Optional. Filter by a specific device if supporting multiple.  
* **Success Response:**  
  * **Code:** `200 OK`  
  * **Body:** An array of downtime event objects. If a camera is currently down, `end_time` can be null.  
    JSON

```
{
  "downtime_history": [
    {
      "camera_id": "Camera-3",
      "start_time": "2025-10-27T08:15:00Z",
      "end_time": "2025-10-27T08:25:00Z", // Camera came back online
      "duration_minutes": 10
    },
    {
      "camera_id": "Camera-2",
      "start_time": "2025-10-27T09:05:00Z",
      "end_time": null, // Camera is currently still offline
      "duration_minutes": null // Duration can be calculated on frontend if needed
    }
    // ... more downtime events
  ]
}
```

  *   
* **Error Responses:** Standard 4xx/5xx codes (see Section 5).  
* **Backend Consideration:** Please detail the proposed logic for detecting and recording the start/end times of camera downtime based on the incoming metrics data. Using the `offline_camera_ids` list would be the most accurate approach if the device can provide it.

**5\. General Requirements & Error Handling**

* **Standard JSON Responses:** All responses should use JSON.  
* **Consistent Error Format:** Failed requests (4xx/5xx status codes) should return a consistent JSON body, for example:  
  JSON

```
{
  "error": "Brief error code or title",
  "message": "Detailed, user-friendly error message",
  "details": "Optional: Additional technical details if applicable"
}
```

*   
* **Performance:** Endpoints retrieving data for the dashboard should respond quickly, ideally within 500ms under normal load. Trend/history endpoints may take longer but should aim for \< 2 seconds.  
* **Timestamp Format:** Please use ISO 8601 format (`YYYY-MM-DDTHH:mm:ssZ`) for all timestamps in requests and responses for consistency.

