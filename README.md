# WatchEdge — ground-Based Observation and Relay (gBOAR🐗)

Wildlife detection system built as a project for the **Network Automation** course (Politecnico di Milano, AY 2025-2026). It uses on-device AI inference to detect animals (wild boar, wolves, deer) from camera feeds, and relays detection events across a 3-tier Edge-Cloud architecture over MQTT.

## Architecture

```text
EXTREME-EDGE ──MQTT──▶ EDGE ──MQTT──▶ CLOUD
 (camera)     (edge/#)  (Mosquitto)   (cloud/#)  (Mosquitto bridge)
                         │                          │
                    Processing Service          Processing Service
                    + PostgreSQL + PostGIS      + PostgreSQL + PostGIS
                    + RustFS (S3)               + RustFS (S3)
                    + Grafana                   + Grafana
                                                 + ItalTel Dashboard
```

| Tier             | What it does                                                                                                               | Stack                                            |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| **Extreme-Edge** | Captures video, runs YOLOv9t ONNX inference, exposes a management WebUI, publishes detection events and telemetry via MQTT | Python, FastAPI, OpenCV, ONNX Runtime, paho-mqtt |
| **Edge**         | Ingests Extreme-Edge messages, persists in PostgreSQL, relays to Cloud, orchestrates image uploads to RustFS               | Python, FastAPI, SQLModel, paho-mqtt, boto3      |
| **Cloud**        | Central aggregation, cross-site image retrieval API, serves the primary dashboard (ItalTel, external to this repository)   | Same as Edge                                     |

## Documentation

| File                                  | Contents                                                                        |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| `doc/Components.md`                   | Full system architecture, component breakdown, BIM references                   |
| `doc/DB_Schema.md`                    | PostgreSQL schema: tables, indexes, trigger, PostGIS geography                  |
| `doc/MQTT_Mapping.md`                 | MQTT topic namespace, payload formats, Mosquitto bridging                       |
| `doc/components/Camera.md`            | Camera software: modules, API routes, threading model, data flows               |
| `doc/components/ProcessingService.md` | Processing service: Edge/Cloud modes, routing, DB operations, image upload flow |

## Repository structure

```text
src/
├── environments/
│   ├── extreme-edge/        # Camera Docker Compose
│   ├── edge/                # Edge stack (Mosquitto + PG + RustFS + processing + Grafana)
│   └── cloud/               # Cloud stack (same components, different ports)
└── services/
    ├── camera/              # Inference + WebUI service
    ├── processing-service/  # Edge/Cloud processing service
    ├── database-postgresql/ # PostgreSQL + PostGIS Docker image
    └── dashboard-grafana/   # Grafana provisioning files
```

## Prerequisites

- Docker and Docker Compose v2
- NVIDIA GPU with CUDA support (optional — falls back to CPU inference)

## Running

### 1. Configure deployment-specific values

| File                                               | What to change                                                                               |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `src/environments/extreme-edge/docker-compose.yml` | `MQTT_HOST`: IP of the Edge Mosquitto broker. `EDGE_ID`, `CAMERA_ID`: provision unique UUIDs |
| `src/environments/edge/docker-compose.yml`         | `OBJECT_STORAGE_URL`, `WEB_BASE_URL`: replace `192.168.178.20` with the Edge host IP         |
| `src/environments/edge/mosquitto/mosquitto.conf`   | `address`: replace `192.168.178.20:1884` with the Cloud Mosquitto endpoint                   |
| `src/environments/cloud/docker-compose.yml`        | `OBJECT_STORAGE_URL`, `WEB_BASE_URL`: replace `192.168.178.20` with the Cloud host IP        |

### 2. Start the stacks

```bash
# 1. Edge (local MQTT broker, database, object storage)
cd src/environments/edge
docker compose up -d

# 2. Cloud and Extreme-Edge (can start in parallel)
cd src/environments/cloud
docker compose up -d

cd src/environments/extreme-edge
docker compose up -d
```

### 3. Access the UIs

| Interface     | URL                               | Default credentials       |
| ------------- | --------------------------------- | ------------------------- |
| Camera WebUI  | `http://<extreme-edge-host>:8080` | —                         |
| Edge Grafana  | `http://<edge-host>:3000`         | `watchedge` / `watchedge` |
| Cloud Grafana | `http://<cloud-host>:3001`        | `watchedge` / `watchedge` |
| Cloud API     | `http://<cloud-host>:8001/health` | —                         |
