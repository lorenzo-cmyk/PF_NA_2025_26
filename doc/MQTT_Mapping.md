# gBOAR - MQTT Topic Mapping Specification

## Topic Namespace Convention

Root structure: `wildlife/{edge_id}/{camera_id}/...`

---

## Phase 1: Connection & Registration ("Birth")

**Trigger:** Device powers on, network connects, or configuration changes.

**Goal:** Register the device in the DB and establish the "Offline" trigger.

1. **Step A: Set Last Will & Testament (LWT)**
    - _Before connecting_, the Edge Client configures the LWT packet.
    - **Topic:** `wildlife/{edge_id}/{camera_id}/telemetry`
    - **Payload:** `{"status": "offline", "timestamp": "1970-01-01T00:00:00Z"}`
    - **QoS:** 1 (Retained)
    - **Broker Action:** Stores this message. It is _only_ published if the
      device disconnects ungracefully.

2. **Step B: Publish Birth Message**
    - **Topic:** `wildlife/{edge_id}/{camera_id}/lifecycle/birth`
    - **Payload:**

      ```json
      {
        "edge_name": "Alps_Sector_04",
        "edge_location": "POINT(45.89 7.22)",
        "camera_type": "TrapCam_v3",
        "camera_coords": "POINT(45.891 7.223)",
        "elevation": 1450,
        "technical_params": { "iso": 800, "res": "4K" }
      }
      ```

    - **QoS:** 1 (Retained)
    - **DB Action:** Upsert (Insert/Update) records in **`edge_device`** and
      **`camera`**.

---

## Phase 2: Operational Monitoring ("Heartbeat")

**Trigger:** Periodic timer (e.g., every 5 minutes).

**Goal:** Report health and confirm "Active" status.

- **Topic:** `wildlife/{edge_id}/{camera_id}/telemetry`
- **Payload:**

  ```json
  {
    "timestamp": "2023-10-27T10:00:00Z",
    "status": "active",
    "temperature": 12.5,
    "battery_level": 94
  }
  ```

- **QoS:** 1 (Retained)
- **DB Action:** Update **`camera`** table (`status`, `temperature`,
  `battery_level`).

---

## Phase 3: Event Detection

**Trigger:** AI Model detects one or more animals.

**Goal:** Persist the event metadata and detection details.

- **Topic:** `wildlife/{edge_id}/{camera_id}/event`
- **Payload:**

  ```json
  {
    "event_id": "evt_uuid_12345",
    "capture_time": "2023-10-27T10:15:00Z",
    "count": 2,
    "event_coordinates": "POINT(45.891 7.223)",
    "detections": [
      {
        "detection_uuid": "det_uuid_98765",
        "animal_type": "wolf",
        "confidence": 0.98,
        "distance": 20,
        "size_estimate": "large"
      },
      {
        "detection_uuid": "det_uuid_98766",
        "animal_type": "wolf",
        "confidence": 0.96,
        "distance": 22,
        "size_estimate": "medium"
      }
    ]
  }
  ```

- **QoS:** 1 (Retained)
- **DB Action:**
  1. Insert into **`dataset_store`** (Note: `image_path` is set to NULL).
  2. Insert rows into **`animal_detected`**.

---

## Phase 4: Image Retrieval (On-Demand)

**Trigger:** User requests image via Dashboard / Automation rule.

**Goal:**: Transfer heavy binary data (image) to Object Storage.

1. **Step A: Cloud Command**
    - **Topic:** `wildlife/{edge_id}/{camera_id}/cmd/upload`
    - **Payload:**

      ```json
      {
        "event_id": "evt_uuid_12345",
        "upload_url": "http://object-storage-s3.cloud/bucket/evt_12345.jpg"
      }
      ```

    - **QoS:** 1 (Retained)

2. **Step B: Edge Execution**
    - Far-edge device locates local file.
    - Far-edge performs `HTTP PUT` to the `upload_url`.

3. **Step C: Upload Status Report**
    - **Topic:** `wildlife/{edge_id}/{camera_id}/event/upload_status`
    - **Payload (Success):**

      ```json
      {
        "event_id": "evt_uuid_12345",
        "status": "SUCCESS",
        "remote_path": "http://object-storage-s3.cloud/bucket/evt_12345.jpg"
      }
      ```

    - **Payload (Failure):**

      ```json
      {
        "event_id": "evt_uuid_12345",
        "status": "ERROR",
        "message": "HTTP 503 Service Unavailable"
      }
      ```

    - **QoS:** 1
    - **DB Action:**
      - _If Success:_ Update **`dataset_store`** set `image_path` =
        `remote_path`.
      - _If Error:_ Log error; do not update path.

---

## Phase 5: Disconnection ("Death")

**Trigger:** Power loss, network failure, crash...

**Goal:** Update DB to reflect the device is offline.

- **Mechanism:** The MQTT Broker detects the connection loss.
- **Action:** Broker automatically publishes the **LWT** message defined in
  Phase 1.
- **Topic:** `wildlife/{edge_id}/{camera_id}/telemetry`
- **Payload:** `{"status": "offline", ...}`
- **DB Action:** Update **`camera`** table set `status` = 'offline'.
