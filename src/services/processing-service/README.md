# Processing Service

Unified Edge / Cloud processing service for the **WatchEdge** wildlife-detection system.
It ingests MQTT messages, persists data in PostgreSQL, manages images in S3-compatible object storage, and exposes an HTTP API.

For the full architecture description see [doc/components/ProcessingService.md](../../../doc/components/ProcessingService.md).

---

## Architecture Role

The same codebase runs in two modes, controlled by `SERVICE_MODE`:

| Mode | Subscribes to | Publishes to | Key responsibilities |
|------|--------------|-------------|----------------------|
| **EDGE** | `edge/#`, `cloud/+/+/cmd/upload` | `cloud/{edge_id}/{camera_id}/…`, `edge/{edge_id}/{camera_id}/cmd/upload` | Ingest Extreme-Edge messages, persist locally, relay to cloud namespace, issue upload commands to camera, fulfil cloud upload requests. |
| **CLOUD** | `cloud/#` | `cloud/{edge_id}/{camera_id}/cmd/upload` | Persist centrally, serve image retrieval API to the Dashboard. |

> **Identity note:** `{edge_id}` and `{camera_id}` are UUID strings provisioned at the Extreme-Edge level (camera service). The processing service has no fixed identity of its own — it extracts both IDs dynamically from each incoming MQTT topic and uses them as database primary keys.

---

## Project Layout

```
processing-service/
├── .env.example                     # Configuration template — copy to .env for local dev
├── main.py                          # CLI entry point (delegates to processing_service.main)
├── pyproject.toml                   # Dependencies & build config
├── Dockerfile
└── processing_service/
    ├── main.py                      # Bootstrap: wires MQTT + HTTP and starts both
    ├── config.py                    # .env / env-var configuration + ServiceMode enum
    ├── mqtt_client.py               # paho-mqtt v2 wrapper
    ├── handlers.py                  # MQTT message handlers — Edge & Cloud routing + DB ops
    ├── database.py                  # SQLModel ORM models + engine/session factories
    ├── s3_client.py                 # boto3 S3-compatible object-storage helper
    └── api.py                       # FastAPI endpoints (health + Cloud image retrieval)
```

---

## Configuration

Configuration is loaded in priority order: **environment variable → `.env` file → built-in default**.

Copy `.env.example` to `.env` and edit for local development. In Docker / production, inject variables as environment variables (the `.env` file is optional and is never required).

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_MODE` | `EDGE` | `EDGE` or `CLOUD`. |
| `MQTT_BROKER_URL` | `mqtt://localhost:1883` | MQTT broker address (`scheme://host:port`). |
| `MQTT_CLIENT_ID` | `processing-service` | MQTT client identifier — must differ between Edge and Cloud instances. |
| `DATABASE_URL` | `postgresql://watchedge:watchedge@localhost:5432/watchedge-db` | PostgreSQL connection string. |
| `OBJECT_STORAGE_URL` | `http://localhost:9000` | S3-compatible endpoint (internal, used for presigned URLs). |
| `S3_PUBLIC_URL` | *(falls back to `OBJECT_STORAGE_URL`)* | Public base URL for stored images (no credentials). |
| `S3_ACCESS_KEY` | `gBOAR` | S3 access key. |
| `S3_SECRET_KEY` | `gBOARpass` | S3 secret key. |
| `S3_BUCKET` | `gboar-images` | S3 bucket name. |
| `WEB_HOST` | `0.0.0.0` | HTTP server bind address. |
| `WEB_PORT` | `8000` | HTTP server bind port. |

---

## HTTP Endpoints

| Method | Path | Mode | Description |
|--------|------|------|-------------|
| `GET` | `/health` | Both | Returns `{"status": "ok", "mode": …, "mqtt_connected": …}`. |
| `GET` | `/api/v1/images/{event_id}` | Cloud | Retrieve a detection image. Serves from Cloud S3 if available; otherwise requests the image from the Edge on-demand (synchronous pull, up to 30 s). |

---

## MQTT Topics

See [MQTT_Mapping.md](../../../doc/MQTT_Mapping.md) for full payload definitions.

### Edge Mode — subscribes to `edge/#` and `cloud/+/+/cmd/upload`

| Incoming topic | Action | Relayed to cloud? |
|----------------|--------|:-----------------:|
| `edge/{eid}/{cid}/lifecycle/birth` | Upsert `edge_device` + `camera` rows | Yes (retained) |
| `edge/{eid}/{cid}/telemetry` | Update camera status / temperature / battery | Yes (retained) |
| `edge/{eid}/{cid}/event` | Insert `datasetstore` + `animaldetected` rows; publish `cmd/upload` to camera | Yes |
| `edge/{eid}/{cid}/event/upload_status` | Update `datasetstore.imagepath` with public URL | No |
| `cloud/{eid}/{cid}/cmd/upload` | Fetch image from Edge S3, HTTP PUT to Cloud S3, publish `upload_status` | — |

### Cloud Mode — subscribes to `cloud/#`

Handles `cloud/` counterparts of birth, telemetry, event, and upload_status with the same DB operations. Does not relay messages.

---

## Database

Four tables (see [DB_Schema.md](../../../doc/DB_Schema.md)):

| Table | Description |
|-------|-------------|
| `edge_device` | Physical edge computing nodes. |
| `camera` | Imaging hardware — child of `edge_device`. |
| `datasetstore` | Captured image events — child of `camera`. |
| `animaldetected` | AI inference results — child of `datasetstore`. |

---

## Object Storage

The S3 bucket is initialised on startup with a **public-read policy** (`s3:GetObject` for all principals). Images are written via presigned PUT URLs (credentials stay on the server side). Paths stored in `datasetstore.imagepath` are clean public URLs without query-string credentials.

---

## Running Locally

```bash
# Install dependencies
uv sync

# Copy and edit configuration
cp .env.example .env

# Start (requires PostgreSQL, Mosquitto, and an S3-compatible storage instance)
uv run processing-service
```

For a full local environment (both Edge and Cloud stacks) use the Docker Compose file at [src/environments/docker-compose.yml](../../environments/docker-compose.yml).
