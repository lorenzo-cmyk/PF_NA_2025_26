# gBOAR - MQTT Topic Mapping Specification

## Introduction to the Namespace

The MQTT topic architecture separates local edge communication from cloud-bound communication using distinct prefixes:

- **`edge/{edge_id}/{camera_id}/...`**: Extreme-Edge to Edge communication.
- **`cloud/{edge_id}/{camera_id}/...`**: Edge to Cloud communication.

## Extreme-Edge -> Edge Messages

Extreme-Edge devices publish raw events and telemetry to the local Edge MQTT Broker.

### 1. Birth / Registration

- **Topic:** `edge/{edge_id}/{camera_id}/lifecycle/birth`
- **Payload:**

  ```json
  {
    "edge_name": "SAN_ROSSORE_PACK_01",
    "edge_location": "POINT(43.76794, 10.324979)",
    "camera_type": "BOAR_CAMERA_V3",
    "camera_coords": "POINT(43.76797, 10.324982)",
    "elevation": 30,
    "technical_params": {
      "iso": 800,
      "res": "2160x3840",
    }
  }
  ```

- **QoS:** 1 (Retained)

### 2. Telemetry & LWT (Heartbeat / Death)

- **Topic:** `edge/{edge_id}/{camera_id}/telemetry`
- **Payload:**

  ```json
  {
    "timestamp": "2026-03-01T10:00:00Z",
    "status": "active",
    "temperature": 17.5,
    "battery_level": 74
  }
  ```

- **QoS:** 1 (Retained)
- **LWT Configuration:** The Extreme-Edge device MUST configure its MQTT client to automatically publish `{"status": "offline"}` to this topic if it ungracefully disconnects.

### 3. Event Detection

- **Topic:** `edge/{edge_id}/{camera_id}/event`
- **Payload:**

  ```json
  {
    "event_id": "EVT_{UUID}",
    "capture_time": "2026-03-01T12:00:00Z",
    "count": 1,
    "event_coordinates": "POINT(43.76797, 10.324982)",
    "detections": [
      {
        "animal_type": "boar",
        "distance": 15.5,
        "size": "big",
        "confidence": 0.92
      }
    ]
  }
  ```

- **QoS:** 1

### 4. Image Upload Status

- **Topic:** `edge/{edge_id}/{camera_id}/event/upload_status`
- **Payload (Success):**

  ```json
  {
    "event_id": "EVT_{UUID}",
    "status": "SUCCESS",
    "remote_path": "http://object-storage-s3.edge/bucket/evt_{UUID}.jpg"
  }
  ```

- **Payload (Failure):**

  ```json
  {
    "event_id": "EVT_{UUID}",
    "status": "ERROR",
    "message": "HTTP 503 Service Unavailable"
  }
  ```

- **QoS:** 1

### 5. Image Upload Command (Edge -> Extreme-Edge)

- **Topic:** `edge/{edge_id}/{camera_id}/cmd/upload`
- **Payload:**

  ```json
  {
    "event_id": "EVT_{UUID}",
    "upload_url": "http://object-storage-s3.edge/bucket/evt_{UUID}.jpg"
  }
  ```

- **QoS:** 1

## Edge -> Cloud Messages

Processed and validated messages intended for the centralized Cloud infrastructure.

- **Birth / Registration:** `cloud/{edge_id}/{camera_id}/lifecycle/birth`
- **Telemetry:** `cloud/{edge_id}/{camera_id}/telemetry`
- **Event Detection:** `cloud/{edge_id}/{camera_id}/event`
- **Image Upload Status:** `cloud/{edge_id}/{camera_id}/event/upload_status`
- **Image Upload Command (Cloud -> Edge):** `cloud/{edge_id}/{camera_id}/cmd/upload`

## The Role of "Edge Processing Service"

The Edge Processing Service acts as the intermediary between the Extreme-Edge and the Cloud namespaces.

- **Subscription:** Subscribes to `edge/#` and `cloud/+/+/cmd/upload` on the local Edge MQTT Broker.
- **Processing:** Ingests, aggregates, validates, and enriches incoming Extreme-Edge events.
- **Publishing:** Publishes the processed data to the corresponding `cloud/#` topics on the same local Edge MQTT Broker.
- **Command Routing:** Receives Cloud commands on `cloud/+/+/cmd/upload` and republishes them down to the Extreme-Edge on `edge/+/+/cmd/upload`.
- **Connection:** Maintains exactly 1 active MQTT session to the local Edge MQTT Broker. It does not connect directly to the Cloud.

## The Role of Mosquitto Bridging

Data transport from the Edge to the Cloud is handled natively by the Mosquitto MQTT Broker via bridging.

- **Topic Forwarding:** The local Edge Mosquitto broker is configured to bridge all `cloud/#` topics to the central Cloud MQTT Broker.
- **Cloud to Edge:** Bridges the `cloud/+/+/cmd/upload` topic from the Cloud Broker down to the Edge Broker without remapping the prefix.
- **Reliability:** Manages queuing, intermittent connectivity, and mutual TLS authentication autonomously, decoupling the Edge Processing Service from network transport concerns.
