# WatchEdge — Processing Service Software Architecture

> **Scope:** This document describes the software design of the **Processing Service** that runs on both Edge and Cloud deployments. It is a single codebase operating in two modes (`EDGE` / `CLOUD`) controlled by an environment variable. The service acts as the intermediary between the Extreme-Edge cameras and the Cloud infrastructure: it ingests MQTT messages, persists data in PostgreSQL, manages images in S3-compatible object storage, relays messages across namespaces, and exposes an HTTP API.

---

## 1. High-Level Overview

The Processing Service is a Python application composed of three subsystems that start concurrently:

1. **MQTT Client** — Connects to the local MQTT broker, subscribes to relevant topics, and dispatches incoming messages to the handler layer.
2. **Message Handler** — Implements all business logic: topic routing, database persistence, MQTT relay (Edge→Cloud namespace), and image upload orchestration.
3. **HTTP API** — A FastAPI server providing a health check endpoint and (in Cloud mode) a REST endpoint for on-demand image retrieval.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                         Processing Service                              │
│                                                                         │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────────┐  │
│  │   MQTT Client    │───>│  Message Handler  │───>│   Database (PG)   │  │
│  │  (paho-mqtt v2)  │    │  (routing + BL)   │    │   via SQLModel    │  │
│  └────────┬─────────┘    └────────┬─────────┘    └───────────────────┘  │
│           │                       │                                     │
│           │ incoming msgs         │ publishes (relay / cmd / status)    │
│           │                       │                                     │
│           v                       v                                     │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────────┐  │
│  │  Topic Dispatch   │    │   S3 Client      │    │  HTTP API         │  │
│  │  (regex router)   │    │   (boto3)        │    │  (FastAPI)        │  │
│  └──────────────────┘    └──────────────────┘    └───────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    SERVICE_MODE switch                           │   │
│  │                                                                  │   │
│  │   EDGE mode:                        CLOUD mode:                  │   │
│  │   • Subscribe edge/#               • Subscribe cloud/#           │   │
│  │   • Subscribe cloud/+/+/cmd/upload  • Persist centrally          │   │
│  │   • Persist locally                 • Serve image retrieval API  │   │
│  │   • Relay edge → cloud namespace   • Issue cmd/upload to Edge    │   │
│  │   • Issue cmd/upload to Extreme-Edge                             │   │
│  │   • Fulfil cloud cmd/upload                                      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module Breakdown

### 2.1 `config.py` — Configuration

Frozen dataclass loaded from environment variables. Exposes derived helpers for MQTT host/port extraction and mode checks.

**Enum: `ServiceMode`**

| Value | Description |
|:------|:------------|
| `EDGE` | Runs as the Edge Processing Service |
| `CLOUD` | Runs as the Cloud Processing Service |

**Class: `Config` (frozen dataclass)**

**Fields:**

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `service_mode` | `ServiceMode` | `EDGE` | Operational mode (`EDGE` or `CLOUD`) |
| `mqtt_broker_url` | `str` | `mqtt://localhost:1883` | MQTT broker address (scheme://host:port) |
| `database_url` | `str` | `postgresql://watchedge:watchedge@localhost:5432/watchedge-db` | PostgreSQL connection string |
| `object_storage_url` | `str` | `http://localhost:9000` | S3-compatible endpoint (internal) |
| `s3_access_key` | `str` | `gBOAR` | S3 access key |
| `s3_secret_key` | `str` | `gBOARpass` | S3 secret key |
| `s3_bucket` | `str` | `gboar-images` | S3 bucket name |
| `s3_public_url` | `str` | `""` (falls back to `object_storage_url`) | Public base URL for stored images (no credentials) |
| `web_host` | `str` | `0.0.0.0` | HTTP server bind address |
| `web_port` | `int` | `8000` | HTTP server bind port |
| `mqtt_client_id` | `str` | `processing-service` | MQTT client identifier |

**Derived helpers (properties):**

| Property | Return Type | Description |
|:---------|:------------|:------------|
| `is_edge` | `bool` | `True` when `service_mode == EDGE` |
| `is_cloud` | `bool` | `True` when `service_mode == CLOUD` |
| `mqtt_host` | `str` | Host extracted from `mqtt_broker_url` |
| `mqtt_port` | `int` | Port extracted from `mqtt_broker_url` (default: `1883`) |

---

### 2.2 `mqtt_client.py` — MQTT Client

Thin wrapper around `paho.mqtt.client` v2. Handles the full MQTT lifecycle: connection, subscriptions, publishing, and message dispatch.

**Class: `MQTTClient`**

**State:**

| Attribute | Type | Description |
|:----------|:-----|:------------|
| `_cfg` | `Config` | Application configuration |
| `_client` | `mqtt.Client` | Underlying paho-mqtt client (CallbackAPIVersion.VERSION2) |
| `_connected` | `bool` | Thread-safe connection state flag |
| `_lock` | `threading.Lock` | Guards `_connected` |
| `_message_callbacks` | `list[MessageCallback]` | Registered message handlers |
| `_subscriptions` | `list[str]` | Topic patterns to subscribe on connect |

**Type alias:** `MessageCallback = Callable[[str, dict[str, Any]], None]` — receives `(topic, payload_dict)`.

**Methods:**

| Method | Description |
|:-------|:------------|
| `connected -> bool` | Property. Thread-safe connection state check. |
| `add_subscription(topic)` | Registers a topic pattern to subscribe to on connect. |
| `on_message(cb)` | Registers a callback invoked for every incoming message. |
| `start()` | Connects to the broker and starts the paho network loop in a background thread via `loop_start()`. |
| `stop()` | Disconnects and stops the network loop. |
| `publish(topic, payload, qos=1, retain=False)` | Publishes a JSON-serialized payload to the given topic. |

**Paho callbacks (internal):**

| Callback | Behavior |
|:---------|:---------|
| `_on_connect` | Sets `_connected = True`, subscribes to all registered topic patterns (QoS 1). |
| `_on_disconnect` | Sets `_connected = False`. |
| `_on_message` | Deserializes JSON payload, invokes all registered `MessageCallback`s. Silently skips non-JSON payloads. |

**Note:** This client does **not** configure an LWT. The Processing Service is not an Extreme-Edge device — it does not publish lifecycle/telemetry messages about itself.

---

### 2.3 `handlers.py` — Message Handler

Contains all business logic: topic parsing, routing by mode, database CRUD, MQTT relay, and upload orchestration. This is the core of the service.

**Class: `MessageHandler`**

**Dependencies:** `Config`, `MQTTClient`, SQLAlchemy `Engine`, `S3Client | None`

**State:**

| Attribute | Type | Description |
|:----------|:-----|:------------|
| `_cfg` | `Config` | Application configuration |
| `_mqtt` | `MQTTClient` | MQTT publishing interface |
| `_engine` | `Engine` | SQLAlchemy engine for database sessions |
| `_s3` | `S3Client \| None` | Object storage client (may be `None` if init failed) |

**Module-level helpers:**

| Helper | Description |
|:-------|:------------|
| `_TOPIC_RE` | Regex `^(edge\|cloud)/(?P<edge_id>...)/(?P<camera_id>...)/(?P<rest>...)$` — extracts prefix, edge_id, camera_id, and remainder from any incoming topic. |
| `_POINT_RE` | Regex to parse `POINT(lon, lat)` strings into `(float, float)`. |
| `_parse_point(value) -> (lon, lat) \| None` | Extracts longitude and latitude from a `POINT(...)` string. |

#### 2.3.1 Entry Point

**`handle(topic, payload)`** — Registered as the sole MQTT message callback. Parses the topic via `_TOPIC_RE`, then dispatches to `_handle_edge()` or `_handle_cloud()` based on `Config.service_mode`.

#### 2.3.2 Edge Mode Routing

**`_handle_edge(prefix, edge_id, camera_id, rest, payload)`**

Routes incoming messages from two subscriptions: `edge/#` and `cloud/+/+/cmd/upload`.

| Incoming Topic Pattern | Handler Called | Relay to Cloud? |
|:-----------------------|:--------------|:----------------|
| `edge/{eid}/{cid}/lifecycle/birth` | `_handle_birth` | **Yes** → `cloud/{eid}/{cid}/lifecycle/birth` (retained) |
| `edge/{eid}/{cid}/telemetry` | `_handle_telemetry` | **Yes** → `cloud/{eid}/{cid}/telemetry` (retained) |
| `edge/{eid}/{cid}/event` | `_handle_event` | **Yes** → `cloud/{eid}/{cid}/event` |
| `edge/{eid}/{cid}/event/upload_status` | `handle_upload_status` | **No** — upload_status is a local Edge concern |
| `edge/{eid}/{cid}/cmd/upload` | *(ignored)* | **No** — these are outgoing commands the service itself publishes |
| `cloud/{eid}/{cid}/cmd/upload` | `_edge_route_cloud_cmd` | **No** — handled locally |

**Relay logic:** After processing an `edge/` message (except `upload_status` and `cmd/upload`), the handler publishes the same payload to the corresponding `cloud/{edge_id}/{camera_id}/{rest}` topic. `lifecycle/birth` and `telemetry` are published as retained; `event` is not.

#### 2.3.3 Cloud Mode Routing

**`_handle_cloud(prefix, edge_id, camera_id, rest, payload)`**

Routes incoming messages from subscription `cloud/#`.

| Incoming Topic Pattern | Handler Called |
|:-----------------------|:--------------|
| `cloud/{eid}/{cid}/lifecycle/birth` | `_handle_birth` |
| `cloud/{eid}/{cid}/telemetry` | `_handle_telemetry` |
| `cloud/{eid}/{cid}/event` | `_handle_event` |
| `cloud/{eid}/{cid}/event/upload_status` | `handle_upload_status` |
| `cloud/{eid}/{cid}/cmd/upload` | *(ignored)* — outgoing commands the service itself publishes |

Cloud mode does **not** relay messages — it is the final destination.

#### 2.3.4 Shared Database Operations

These handlers are identical in Edge and Cloud mode — the same DB schema is used at both tiers.

**`_handle_birth(edge_id, camera_id, payload)`**

Upserts rows in `edge_device` and `camera` tables. Both `edge_id` and `camera_id` arrive as UUID strings extracted from the MQTT topic and are parsed into `uuid.UUID` objects.

1. Looks up `edge_device` by PK (`edge_id`). If not found, inserts a new row using the topic UUID as PK. If found, updates `name`/`location` from payload fields `edge_name`/`edge_location`.
2. Flushes (so the parent FK exists).
3. Looks up `camera` by PK (`camera_id`). If not found, inserts a new row using the topic UUID as PK, with `edge_id` FK pointing to the parent. If found, updates `type`/`technical_params_json`/`elevation`. Always sets `status = "Online"`.
4. If `camera_coords` is present, updates `location_coordinates` via raw SQL (`ST_SetSRID(ST_MakePoint(...), 4326)::geography`) because PostGIS GEOGRAPHY columns are not mapped in SQLModel.
5. Commits.

**`_handle_telemetry(camera_id, payload)`**

Updates the `camera` row:

1. Parses `camera_id` as UUID; looks up the camera by PK. Skips if not found (telemetry before birth).
2. Updates `status`, `temperature`, `battery_level` from payload fields if present.
3. Commits.

**`_handle_event(edge_id, camera_id, payload)`**

Inserts a `datasetstore` row and its child `animaldetected` rows:

1. Extracts `event_id` from payload (must be a valid UUID).
2. Parses `camera_id` as UUID; looks up the camera by PK. Skips if not found (event before birth).
3. Checks for duplicate `event_id` — skips if already exists.
4. Inserts `datasetstore` with `imagepath = ""` (image not yet uploaded), `time` from `capture_time`, `count` from payload (informational — the DB trigger `trg_refresh_count` recomputes it).
5. Flushes (parent must exist for FK).
6. For each detection in `payload["detections"]`, inserts an `animaldetected` child row with `animal_type`, `distance`, `size_estimate`, `confidence`.
7. Commits.
8. **Edge mode only:** After successful DB insertion, generates a presigned PUT URL via S3Client and publishes a `cmd/upload` command to `edge/{edge_id}/{camera_id}/cmd/upload` so the Extreme-Edge camera uploads its image to the Edge Object Storage.

**`handle_upload_status(payload)`**

Updates `datasetstore.imagepath` on successful image upload:

1. Checks `status` field — only processes `"SUCCESS"`.
2. Derives the clean public URL (no credentials) from the S3 client: `{s3_public_url}/{bucket}/{event_id}.jpg`.
3. Looks up the `datasetstore` row by `event_id`.
4. Sets `imagepath` to the public URL.
5. Commits.

#### 2.3.5 Edge-Specific: Cloud Upload Command Fulfillment

**`_edge_route_cloud_cmd(edge_id, camera_id, payload)`**

When the Cloud requests an image via `cloud/{eid}/{cid}/cmd/upload`, the Edge Processing Service fulfils the request locally (it has access to the local Edge Object Storage):

1. Extracts `event_id` and `upload_url` (presigned Cloud S3 URL) from payload.
2. Downloads the image (`{event_id}.jpg`) from the local Edge S3 via `S3Client.get_object()`.
3. Uploads the image bytes to the Cloud S3 via HTTP PUT to the `upload_url`.
4. Publishes the result to `cloud/{edge_id}/{camera_id}/event/upload_status`:
   - On success: `{"event_id": ..., "status": "SUCCESS", "remote_path": <URL without query params>}`
   - On failure: `{"event_id": ..., "status": "ERROR", "message": <error description>}`

---

### 2.4 `database.py` — Database Models & Engine

SQLModel-based ORM models matching the WatchEdge DB schema. The four tables are:

| Model | Table | PK | Parent FK |
|:------|:------|:---|:----------|
| `EdgeDevice` | `edge_device` | `edge_id` (UUID) | — |
| `Camera` | `camera` | `camera_id` (UUID) | `edge_device.edge_id` |
| `DatasetStore` | `datasetstore` | `event_id` (UUID) | `camera.camera_id` |
| `AnimalDetected` | `animaldetected` | `detection_id` (UUID) | `datasetstore.event_id` |

**Note:** `Camera.location_coordinates` (PostGIS `GEOGRAPHY(Point, 4326)`) is **not** mapped in the SQLModel class — it is handled via raw SQL in `_handle_birth`.

**Factory functions:**

| Function | Description |
|:---------|:------------|
| `get_engine(database_url) -> Engine` | Creates a SQLAlchemy engine. |
| `get_session(engine) -> Session` | Creates a new SQLModel `Session`. |

---

### 2.5 `s3_client.py` — S3 Object Storage Client

Wrapper around `boto3` for S3-compatible object storage (RustFS). Used for both reading and writing images, and for generating presigned URLs.

**Class: `S3Client`**

**Dependencies:** `boto3`, `botocore`

**State:**

| Attribute | Type | Description |
|:----------|:-----|:------------|
| `_cfg` | `Config` | Application configuration |
| `_client` | `boto3.client` | Configured S3 client (path-style addressing, s3v4 signatures) |
| `_bucket` | `str` | Bucket name |
| `_public_base` | `str` | Public URL base (from `s3_public_url` or `object_storage_url`) |

**Initialization behavior:**

1. Creates the boto3 S3 client with path-style addressing and `s3v4` signature.
2. Ensures the configured bucket exists (creates it if missing).
3. Applies a **public-read policy** (`s3:GetObject` for `Principal: *`) so stored images are publicly accessible without credentials.

**Methods:**

| Method | Description |
|:-------|:------------|
| `generate_presigned_upload_url(object_key, expires_in=3600) -> str` | Generates a presigned PUT URL for uploading an object. |
| `generate_presigned_download_url(object_key, expires_in=3600) -> str` | Generates a presigned GET URL for downloading an object. |
| `object_exists(object_key) -> bool` | Checks whether an object exists in the bucket. |
| `get_object(object_key) -> bytes \| None` | Downloads an object and returns its bytes, or `None` if not found. |
| `get_object_url(object_key) -> str` | Returns the clean public URL of an object: `{_public_base}/{bucket}/{key}`. |

---

### 2.6 `api.py` — HTTP API (FastAPI)

FastAPI application providing a health check (both modes) and an image retrieval endpoint (Cloud mode only). Receives shared state from `main.py` via `init()`.

**Module-level state (set by `init()`):**

| Variable | Type | Description |
|:---------|:-----|:------------|
| `_cfg` | `Config` | Application configuration |
| `_mqtt` | `MQTTClient` | MQTT client reference |
| `_engine` | `Engine` | SQLAlchemy DB engine |
| `_s3` | `S3Client \| None` | S3 client reference |
| `_upload_events` | `dict[str, threading.Event]` | Pending upload completion waiters (Cloud mode) |
| `_upload_lock` | `threading.Lock` | Guards `_upload_events` |

**Function: `init(cfg, mqtt_client, engine, s3)`** — Wires up the shared state before the FastAPI app starts.

**Function: `notify_upload_complete(event_id)`** — Signals a waiting `threading.Event` that an image upload has completed for the given `event_id`. Called from `main.py` when an `upload_status` with `status == "SUCCESS"` arrives (via a monkey-patched wrapper around `handler.handle_upload_status`).

#### Endpoints

| Method | Path | Mode | Description |
|:-------|:-----|:-----|:------------|
| `GET` | `/health` | Both | Returns `{"status": "ok", "mode": ..., "mqtt_connected": ...}`. |
| `GET` | `/api/v1/images/{event_id}` | Cloud only | Retrieves an event image. See below for the full flow. |

#### Image Retrieval Flow (`GET /api/v1/images/{event_id}`)

This endpoint is the mechanism by which the Dashboard (or any Cloud consumer) obtains detection images. It implements a **synchronous on-demand pull** pattern:

```
1. Validate event_id is a UUID.
2. Look up DatasetStore row in DB.
   └── 404 if not found.
3. If imagepath is set AND the object exists in Cloud S3:
   └── Return image bytes directly (cache hit).
4. Otherwise (image not yet in Cloud storage):
   a. Resolve edge_id from camera_id via DB lookup.
   b. Register a threading.Event waiter for this event_id.
   c. Generate a presigned Cloud S3 upload URL.
   d. Publish cmd/upload to cloud/{edge_id}/{camera_id}/cmd/upload.
      (Mosquitto bridge carries this down to the Edge broker;
       the Edge Processing Service fulfils it.)
   e. Wait up to 30 seconds for the upload_status notification.
      └── 504 Timeout if not received.
   f. Re-read imagepath from DB.
   g. Fetch image bytes from Cloud S3 (or fallback: HTTP GET imagepath).
      └── 502 if fetch fails.
   h. Return image bytes.
5. Always: clean up the waiter from _upload_events.
```

**Helper: `_try_fetch_image(url) -> bytes | None`** — HTTP GET fallback to fetch an image from a URL. Returns bytes on 200, `None` on error.

**Helper: `_resolve_edge_id(camera_id: UUID) -> UUID | None`** — Looks up the `edge_id` FK for a given camera PK from the `camera` table. The returned UUID is used directly in the MQTT topic.

---

### 2.7 `main.py` — Application Entry Point

Orchestrates startup and wiring of all components.

**Startup sequence:**

```
1.  Load Config from environment variables
2.  Create SQLAlchemy engine from database_url
3.  Create S3Client (graceful degradation: if init fails, image features are disabled)
4.  Create MQTTClient(config)
5.  Create MessageHandler(config, mqtt, engine, s3)
6.  [Cloud mode only] Monkey-patch handler.handle_upload_status to also call
    api.notify_upload_complete(event_id) on SUCCESS — this wakes up any
    waiting /api/v1/images/{event_id} request
7.  Register MessageHandler.handle as the sole MQTT message callback
8.  Configure subscriptions based on mode:
      EDGE  → subscribe("edge/#"), subscribe("cloud/+/+/cmd/upload")
      CLOUD → subscribe("cloud/#")
9.  Wire up API module: api.init(cfg, mqtt, engine, s3)
10. Start MQTT client (background loop; graceful if broker unreachable)
11. Start FastAPI/Uvicorn (blocks on main thread)
```

---

## 3. File Structure

```
src/services/processing-service/
├── Dockerfile
├── main.py                          # CLI entry point (delegates to processing_service.main)
├── pyproject.toml                   # Dependencies & build config
├── README.md
└── processing_service/              # Application package
    ├── __init__.py
    ├── main.py                      # Bootstrap (MQTT + HTTP)
    ├── config.py                    # Env-var configuration + ServiceMode enum
    ├── mqtt_client.py               # paho-mqtt v2 wrapper
    ├── handlers.py                  # MQTT message handlers (Edge & Cloud routing + DB ops)
    ├── database.py                  # SQLModel ORM models + engine/session factories
    ├── s3_client.py                 # boto3 S3-compatible object storage helper
    └── api.py                       # FastAPI endpoints (health + Cloud image retrieval)
```

---

## 4. Dependencies

| Package | Purpose |
|:--------|:--------|
| `fastapi` | HTTP API framework |
| `uvicorn[standard]` | ASGI server |
| `paho-mqtt` | MQTT v5 client (v2 API) |
| `sqlmodel` | ORM models and database sessions (wraps SQLAlchemy) |
| `psycopg2-binary` | PostgreSQL driver |
| `requests` | HTTP PUT/GET for image upload/download |
| `boto3` | S3-compatible object storage client |

---

## 5. Threading Model

```
Main Thread          ─── Uvicorn / FastAPI (blocking)
                          ├── GET /health
                          └── GET /api/v1/images/{event_id}
                                └── May block up to 30 s waiting for upload completion
                                    (via threading.Event, run_in_executor)

MQTT Loop Thread     ─── paho-mqtt network loop (daemon, started by loop_start())
                          └── Receives messages → MessageHandler.handle()
                                ├── DB writes (birth, telemetry, event, upload_status)
                                ├── MQTT publishes (relay, cmd/upload, upload_status)
                                └── HTTP PUT for cloud cmd/upload fulfillment (blocking)
```

Shared state:

- `MQTTClient._connected` — guarded by `threading.Lock`.
- `api._upload_events` — guarded by `api._upload_lock`.

**Note:** The current implementation performs HTTP PUT (for cloud upload command fulfillment) synchronously inside the MQTT callback thread. This blocks MQTT message processing during the upload. A future improvement could offload this to a worker thread.

---

## 6. Data Flow Diagrams

### 6.1 Edge Mode: Event Ingestion & Relay

```
Extreme-Edge Camera
     │
     │  MQTT: edge/{eid}/{cid}/event
     v
MQTT Broker (Edge)
     │
     v
MQTTClient._on_message()
     │
     v
MessageHandler._handle_edge()
     │
     ├── _handle_event()
     │     ├── INSERT datasetstore + animaldetected rows (PostgreSQL)
     │     └── Publish cmd/upload → edge/{eid}/{cid}/cmd/upload
     │           (presigned Edge S3 URL so camera uploads its image)
     │
     └── Relay → cloud/{eid}/{cid}/event
           │
           v
     MQTT Broker (Edge) → Mosquitto Bridge → MQTT Broker (Cloud)
```

### 6.2 Edge Mode: Image Upload Flow (Extreme-Edge → Edge S3)

```
Processing Service publishes:  edge/{eid}/{cid}/cmd/upload
     │                          {"event_id": ..., "upload_url": <presigned Edge S3 PUT>}
     v
Extreme-Edge Camera
     │
     ├── HTTP PUT image → Edge Object Storage (upload_url)
     │
     └── MQTT: edge/{eid}/{cid}/event/upload_status
              {"event_id": ..., "status": "SUCCESS", "remote_path": ...}
              │
              v
         MessageHandler.handle_upload_status()
              └── UPDATE datasetstore.imagepath = public URL
```

### 6.3 Edge Mode: Cloud Upload Command Fulfillment

```
Cloud Processing Service publishes:  cloud/{eid}/{cid}/cmd/upload
     │                                {"event_id": ..., "upload_url": <presigned Cloud S3 PUT>}
     │
     v  (Mosquitto bridge carries it down to Edge broker)
     │
Edge Processing Service receives:  cloud/{eid}/{cid}/cmd/upload
     │
     v
MessageHandler._edge_route_cloud_cmd()
     │
     ├── S3Client.get_object("{event_id}.jpg")     ← Download from Edge S3
     ├── HTTP PUT image bytes → upload_url          ← Upload to Cloud S3
     │
     └── Publish cloud/{eid}/{cid}/event/upload_status
           {"event_id": ..., "status": "SUCCESS", "remote_path": ...}
           │
           v  (Mosquitto bridge carries it up to Cloud broker)
           │
     Cloud Processing Service receives upload_status
           ├── UPDATE datasetstore.imagepath = public URL
           └── notify_upload_complete(event_id)  → wakes waiting API request
```

### 6.4 Cloud Mode: On-Demand Image Retrieval

```
Dashboard (or any consumer)
     │
     │  GET /api/v1/images/{event_id}
     v
FastAPI endpoint
     │
     ├── [Cache hit] Image exists in Cloud S3
     │     └── Return image bytes immediately
     │
     └── [Cache miss] Image not yet in Cloud S3
           │
           ├── Publish cmd/upload → cloud/{eid}/{cid}/cmd/upload
           │     (presigned Cloud S3 URL; Mosquitto bridge → Edge)
           │
           ├── Wait (threading.Event, up to 30 s)
           │     └── Woken by notify_upload_complete(event_id)
           │
           └── Fetch image from Cloud S3 → Return to caller
```

---

## 7. MQTT Subscription & Publishing Summary

### Edge Mode

**Subscribes to:**

| Topic Pattern | Purpose |
|:--------------|:--------|
| `edge/#` | All Extreme-Edge messages (birth, telemetry, event, upload_status) |
| `cloud/+/+/cmd/upload` | Cloud upload commands forwarded down by Mosquitto bridge |

**Publishes to:**

| Topic | QoS | Retained | Trigger |
|:------|:----|:---------|:--------|
| `cloud/{eid}/{cid}/lifecycle/birth` | 1 | Yes | On receiving `edge/.../lifecycle/birth` |
| `cloud/{eid}/{cid}/telemetry` | 1 | Yes | On receiving `edge/.../telemetry` |
| `cloud/{eid}/{cid}/event` | 1 | No | On receiving `edge/.../event` |
| `edge/{eid}/{cid}/cmd/upload` | 1 | No | After storing an event (instructs camera to upload image) |
| `cloud/{eid}/{cid}/event/upload_status` | 1 | No | After fulfilling a cloud `cmd/upload` |

### Cloud Mode

**Subscribes to:**

| Topic Pattern | Purpose |
|:--------------|:--------|
| `cloud/#` | All relayed messages (birth, telemetry, event, upload_status) |

**Publishes to:**

| Topic | QoS | Retained | Trigger |
|:------|:----|:---------|:--------|
| `cloud/{eid}/{cid}/cmd/upload` | 1 | No | On-demand image retrieval via `GET /api/v1/images/{event_id}` |

---

## 8. Identity Model — Pure UUID Identifiers

All entity identifiers are **UUIDs end-to-end**. The same UUID appears in the MQTT topic, the message payloads, and the database primary key — there is no mapping layer.

| Entity | MQTT topic segment | DB column | Generated by |
|:-------|:-------------------|:----------|:-------------|
| Edge device | `{edge_id}` (UUID) | `edge_device.edge_id` (PK) | Provisioned at deployment time (env var) |
| Camera | `{camera_id}` (UUID) | `camera.camera_id` (PK) | Provisioned at deployment time (env var) |
| Event | — (in payload) | `datasetstore.event_id` (PK) | Generated by the camera on each detection (`uuid.uuid4()`) |
| Detection | — | `animaldetected.detection_id` (PK) | Generated by the Processing Service on insert (`uuid.uuid4()`) |

**Topic example:** `edge/a3f1b2c4-...-d5e6/7c8d9e0f-...-a1b2/event`

Because identifiers are UUIDs from the start, the Processing Service can look up or insert DB rows by **primary key directly** — no secondary lookup column is needed. The existing DB schema (`init.sql`) requires **no modifications**.

On `_handle_birth`, the handler parses the topic's `edge_id` / `camera_id` segments as `uuid.UUID`, then performs a PK-based `session.get()`. If the row does not exist, it is inserted using that same UUID as the PK; if it does exist, it is updated (upsert).

---

## 9. Graceful Degradation

| Component | Failure Mode | Behavior |
|:----------|:-------------|:---------|
| **S3 Client** | Initialization fails | `s3` is set to `None`. Image features (upload commands, image retrieval) are disabled. All other functionality (DB persistence, MQTT relay) continues. |
| **MQTT Broker** | Unreachable at startup | HTTP server starts anyway. MQTT features are unavailable until reconnection (paho-mqtt handles auto-reconnect). |
| **Database** | Query fails | Individual handler catches the exception and logs it. The message is effectively dropped but the service continues processing subsequent messages. |
