# WatchEdge Processing Service

Dual-mode (Edge / Cloud) processing service for the **WatchEdge** wildlife-detection system.
It ingests MQTT messages from the Camera Service, persists data in PostgreSQL, manages detection images in S3-compatible object storage, and exposes an HTTP API.

## Features

- **Dual-mode operation** — the same codebase runs as an Edge processor (next to the cameras) or as a Cloud processor (central aggregator), selected via `SERVICE_MODE`.
- **MQTT ingestion** — subscribes to camera lifecycle, telemetry, event, and upload-status topics; relays messages across the Edge → Cloud boundary.
- **Image upload orchestration** — Edge mode triggers the Camera Service to upload JPEG snapshots; Cloud mode fetches images from Edge S3 and stores them centrally.
- **PostgreSQL persistence** — stores edge devices, cameras, detection events, and animal inference results via SQLModel ORM.
- **S3-compatible object storage** — presigned PUT URLs keep credentials server-side; stored paths are clean public URLs.
- **REST API** — health check available in both modes; on-demand image retrieval endpoint in Cloud mode.

## Architecture

```text
[Camera Service]
      │ MQTT (edge/#)
      ▼
 MQTTClient ──► Handlers ──► Database (PostgreSQL)
                   │               │
                   │        S3Client (RustFS / S3)
                   │
                   └──► relay ──► MQTT (cloud/#)
                                       │
                                  [Cloud MQTTClient]
                                       ▼
                                  Handlers ──► Database (PostgreSQL)
                                                    │
                                             S3Client (Cloud S3)
                                                    │
                                               API (FastAPI)
```

| Module           | Responsibility                                                                    |
| ---------------- | --------------------------------------------------------------------------------- |
| `config.py`      | Loads and validates all settings from `.env` / environment; defines `ServiceMode` |
| `mqtt_client.py` | paho-mqtt v2 wrapper — subscribe, publish, connection lifecycle                   |
| `handlers.py`    | MQTT message handlers — Edge & Cloud routing, DB writes, image upload logic       |
| `database.py`    | SQLModel ORM models and engine/session factories                                  |
| `s3_client.py`   | boto3 S3-compatible helper — bucket init, presigned URLs, direct upload           |
| `api.py`         | FastAPI app — health check and Cloud image retrieval endpoint                     |

## MQTT Topics

All edge topics follow the pattern `edge/{edge_id}/{camera_id}/…` and cloud topics follow `cloud/{edge_id}/{camera_id}/…`. See [MQTT_Mapping.md](../../../doc/MQTT_Mapping.md) for full payload definitions.

### Edge mode — subscribes to `edge/#` and `cloud/+/+/cmd/upload`

| Topic                                  | Action                                                                        | Relayed to cloud? |
| -------------------------------------- | ----------------------------------------------------------------------------- | :---------------: |
| `edge/{eid}/{cid}/lifecycle/birth`     | Upsert `edge_device` + `camera` rows                                          |  Yes (retained)   |
| `edge/{eid}/{cid}/telemetry`           | Update camera status, temperature, battery                                    |  Yes (retained)   |
| `edge/{eid}/{cid}/event`               | Insert `datasetstore` + `animaldetected` rows; publish `cmd/upload` to camera |        Yes        |
| `edge/{eid}/{cid}/event/upload_status` | Update `datasetstore.imagepath` with public URL                               |        No         |
| `cloud/{eid}/{cid}/cmd/upload`         | Fetch image from Edge S3, PUT to Cloud S3, publish `upload_status`            |         —         |

### Cloud mode — subscribes to `cloud/#`

Handles the `cloud/` counterparts of birth, telemetry, event, and upload_status with the same DB operations. Does not relay messages.

## Configuration

Settings are read from a `.env` file in the project root (or from environment variables).

| Variable             | Default                                                        | Description                                                                                                        |
| -------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `SERVICE_MODE`       | `EDGE`                                                         | Operational mode: `EDGE` or `CLOUD`                                                                                |
| `MQTT_HOST`          | `localhost`                                                    | MQTT broker hostname                                                                                               |
| `MQTT_PORT`          | `1883`                                                         | MQTT broker port                                                                                                   |
| `MQTT_USERNAME`      | _(none)_                                                       | Broker username; leave empty for anonymous connections                                                             |
| `MQTT_PASSWORD`      | _(none)_                                                       | Broker password                                                                                                    |
| `MQTT_CLIENT_ID`     | _(auto)_                                                       | MQTT client ID — must differ between Edge and Cloud instances                                                      |
| `DATABASE_URL`       | `postgresql://watchedge:watchedge@localhost:5432/watchedge-db` | PostgreSQL connection string                                                                                       |
| `OBJECT_STORAGE_URL` | `http://localhost:9000`                                        | S3-compatible endpoint (MUST be accessible by BOTH Camera and processing-service)                                  |
| `S3_PUBLIC_URL`      | _(falls back to `OBJECT_STORAGE_URL`)_                         | Public base URL for stored images (no credentials). MUST be reachable by the operator client.                      |
| `S3_ACCESS_KEY`      | `watchedge`                                                    | S3 access key                                                                                                      |
| `S3_SECRET_KEY`      | `watchedge`                                                    | S3 secret key                                                                                                      |
| `S3_BUCKET`          | `watchedge-images`                                             | S3 bucket name                                                                                                     |
| `WEB_HOST`           | `0.0.0.0`                                                      | HTTP server bind address                                                                                           |
| `WEB_PORT`           | `8000`                                                         | HTTP server port                                                                                                   |
| `WEB_BASE_URL`       | `http://localhost:8000`                                        | External base URL for the service UI. MUST be reachable by the operator client (not used for filtering/validation) |

Minimal `.env` example:

```dotenv
SERVICE_MODE=EDGE
MQTT_HOST=mqtt.example.com
DATABASE_URL=postgresql://watchedge:watchedge@db:5432/watchedge-db
OBJECT_STORAGE_URL=http://rustfs:9000
```

## Running

### Local (development)

```bash
# Install dependencies (Python 3.14.3+)
uv sync

# Edit .env with your local PostgreSQL, Mosquitto, and object storage endpoints
# (A default .env is provided in the repository)

uv run processing-service
```

### Docker

```bash
docker build -t watchedge-processing-service .

docker run --rm \
  -e SERVICE_MODE=EDGE \
  -e MQTT_HOST=mqtt.example.com \
  -e DATABASE_URL=postgresql://watchedge:watchedge@db:5432/watchedge-db \
  -e OBJECT_STORAGE_URL=http://rustfs:9000 \
  -p 8000:8000 \
  watchedge-processing-service
```

For a full local environment (both Edge and Cloud stacks) use the Docker Compose file at [src/environments/docker-compose.yml](../../environments/docker-compose.yml).

## REST API

All endpoints are served by the FastAPI app.

| Method | Path                        | Mode  | Description                                                                                                                                        |
| ------ | --------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`  | `/health`                   | Both  | Returns `{"status": "ok", "mode": …, "mqtt_connected": …}`                                                                                         |
| `GET`  | `/api/v1/images/{event_id}` | Cloud | Retrieve a detection image. Serves from Cloud S3 if available; otherwise requests an on-demand upload from the Edge (synchronous pull, up to 30 s) |

Interactive API docs are available at `http://<host>:8000/docs`.
