# Processing Service

Unified Edge / Cloud processing service for the **gBOAR** wildlife-detection system.
It ingests MQTT messages, persists data in PostgreSQL, manages images in S3-compatible object storage, and exposes an HTTP API.

## Architecture Role

The same codebase runs in two modes controlled by the `SERVICE_MODE` environment variable:

| Mode      | Subscribes to                    | Publishes to                             | Key responsibilities                                                                            |
| --------- | -------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **EDGE**  | `edge/#`, `cloud/+/+/cmd/upload` | `cloud/{edge_id}/{camera_id}/…`          | Ingest extreme-edge messages, persist locally, relay to cloud namespace, route upload commands. |
| **CLOUD** | `cloud/#`                        | `cloud/{edge_id}/{camera_id}/cmd/upload` | Persist centrally, serve image retrieval API for the Dashboard.                                 |

## Project Layout

```
processing-service/
├── main.py                          # CLI entry point
├── pyproject.toml                   # Dependencies & build config
├── Dockerfile
└── processing_service/              # Application package
    ├── main.py                      # Bootstrap (MQTT + HTTP)
    ├── config.py                    # Env-var configuration
    ├── mqtt_client.py               # paho-mqtt v2 wrapper
    ├── handlers.py                  # MQTT message handlers (edge & cloud)
    ├── database.py                  # SQLModel models & engine setup
    ├── s3_client.py                 # S3-compatible object-storage helper
    └── api.py                       # FastAPI endpoints
```

## Environment Variables

| Variable             | Default                                         | Description                        |
| -------------------- | ----------------------------------------------- | ---------------------------------- |
| `SERVICE_MODE`       | `EDGE`                                          | `EDGE` or `CLOUD`.                 |
| `MQTT_BROKER_URL`    | `mqtt://localhost:1883`                         | MQTT broker address.               |
| `MQTT_CLIENT_ID`     | `processing-service`                            | MQTT client identifier.            |
| `DATABASE_URL`       | `postgresql://gBOAR:gBOAR@localhost:5432/gBOAR` | PostgreSQL connection string.      |
| `OBJECT_STORAGE_URL` | `http://localhost:9000`                         | S3-compatible endpoint (internal). |
| `S3_PUBLIC_URL`      | *(falls back to `OBJECT_STORAGE_URL`)*          | Public base URL for stored images. |
| `S3_ACCESS_KEY`      | `gBOAR`                                         | S3 access key.                     |
| `S3_SECRET_KEY`      | `gBOARpass`                                     | S3 secret key.                     |
| `S3_BUCKET`          | `gboar-images`                                  | S3 bucket name.                    |
| `WEB_HOST`           | `0.0.0.0`                                       | HTTP listen address.               |
| `WEB_PORT`           | `8000`                                          | HTTP listen port.                  |

## HTTP Endpoints

| Method | Path                        | Mode  | Description                                                    |
| ------ | --------------------------- | ----- | -------------------------------------------------------------- |
| `GET`  | `/health`                   | Both  | Health check returning service mode and MQTT status.           |
| `GET`  | `/api/v1/images/{event_id}` | Cloud | Retrieve an event image (from storage or on-demand from edge). |

## MQTT Topics Handled

See [MQTT_Mapping.md](../../../doc/MQTT_Mapping.md) for full payload definitions.

### Edge Mode

- **`edge/{edge_id}/{camera_id}/lifecycle/birth`** — Upsert edge device & camera in DB.
- **`edge/{edge_id}/{camera_id}/telemetry`** — Update camera status / temperature / battery.
- **`edge/{edge_id}/{camera_id}/event`** — Store detection event + animal records; issue `cmd/upload`.
- **`edge/{edge_id}/{camera_id}/event/upload_status`** — Update `image_path` with public URL on success.
- **`cloud/+/+/cmd/upload`** — Route cloud upload commands down to extreme-edge.

All processed `edge/` messages are relayed to the `cloud/` namespace.

### Cloud Mode

Handles `cloud/` counterparts of the above topics with the same DB operations.

## Database

Four tables are used (see [DB_Schema.md](../../../doc/DB_Schema.md)):

1. **`edge_device`** — Physical edge nodes.
2. **`camera`** — Imaging hardware (child of `edge_device`).
3. **`dataset_store`** — Captured image events (child of `camera`).
4. **`animal_detected`** — AI inference results (child of `dataset_store`).

## Object Storage

The bucket is configured as **publicly readable** (anonymous `GetObject`) but **writable only with credentials** (presigned PUT URLs).
Image paths stored in the database (`dataset_store.image_path`) are clean public URLs without credentials.

## Running Locally

```bash
# Install dependencies
uv sync

# Start (requires PostgreSQL, Mosquitto, and S3-compatible storage)
uv run processing-service
```
