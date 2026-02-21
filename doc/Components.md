# gBOAR - System Components & Architecture

## Architecture Diagram

```text
+-----------------------------------------------------------------------+
|                            EXTREME-EDGE                               |
|                                                                       |
|  +-----------------------------------------------------------------+  |
|  |        Camera Management System & AI Detection Software         |  |
|  +-------------------------------+---------------------------------+  |
|                                  |                                    |
|  +-------------------------------+---------------------------------+  |
|  |               gBOAR Library (Python MQTT Client)                |  |
|  +-------------------------------+---------------------------------+  |
+----------+------------------------------------------+-----------------+
           ^                                          |
           | MQTT                                     | HTTP
           v                                          v
+----------+------------------------------------------+-----------------+
|                                EDGE                                   |
|                                                                       |
|  +-----------------------+                  +----------------------+  |
|  | MQTT Broker           |                  | Object Storage       |  |
|  | (Mosquitto)           |                  | (RustFS)             |  |
|  | [ENDPOINT]            |                  | [ENDPOINT]           |  |
|  +--+-----------------+--+                  +----------------------+  |
|     |                 ^                                               |
|     | MQTT            | MQTT                                          |
|     v                 |                                               |
|  +-----------------------+                  +----------------------+  |
|  | Edge Processing       +----------------->| SQL Database         |  |
|  | Service               |       SQL        | (PostgreSQL)         |  |
|  +-----------+-----------+                  +----------------------+  |
+----------+---|--------------------------------------------------------+
           ^   |
           |   | HTTP
           |   +------------------------------------------------------+
           | MQTT                                                     |
           v                                                          v
+----------+----------------------------------------------------------+-+
|                               CLOUD                                   |
|                                                                       |
|  +-----------------------+                  +----------------------+  |
|  | MQTT Broker           |                  | Object Storage       |  |
|  | (Mosquitto)           |                  | (RustFS)             |  |
|  | [ENDPOINT]            |                  | [ENDPOINT]           |  |
|  +--+-----------------+--+                  +----------+-----------+  |
|     |                 ^                                ^              |
|     | MQTT            | MQTT                           | HTTP         |
|     v                 |                                |              |
|  +-----------------------+                  +----------+-----------+  |
|  | Cloud Processing      +----------------->| SQL Database         |  |
|  | Service               |       SQL        | (PostgreSQL)         |  |
|  +-----------+-----------+                  +----------------------+  |
|              |                                                        |
|              | HTTP                                                   |
|  +-----------v-----------------------------------------------------+  |
|  | Dashboard (ItalTel Blackbox)                                    |  |
|  | [ENDPOINT]                                                      |  |
|  +-----------------------------------------------------------------+  |
+-----------------------------------------------------------------------+
```

## Component Breakdown

### Extreme-Edge

- **Camera Management System & AI Detection Software**: Handles image capture and local AI inference.
- **gBOAR Library**: Python library enabling the CMS to communicate with the network via MQTT. Publishes lifecycle (`birth`), `telemetry` (with LWT configured), and `event` data to the `edge/{edge_id}/{camera_id}/...` namespace. Accepts commands on `edge/{edge_id}/{camera_id}/cmd/upload` to upload files using HTTP POST to the Edge Object Storage.

### Edge

- **MQTT Broker (Mosquitto) [ENDPOINT]**: Local broker for Extreme-Edge to Edge communication. Configured to bridge all `cloud/#` topics up to the Cloud MQTT Broker, and bridge `cloud/+/+/cmd/upload` commands from the Cloud down to the Edge without remapping. Manages queuing and mutual TLS autonomously.
- **SQL Database (PostgreSQL)**: Local persistence for events and metadata. Stores data according to the `edge_device`, `camera`, `dataset_store`, and `animal_detected` schema.
- **Object Storage (RustFS) [ENDPOINT]**: Local storage for captured images.
- **Edge Processing Service**: Intermediary service maintaining exactly 1 active MQTT session to the local broker. Subscribes to `edge/#`, ingests, aggregates, validates, and enriches incoming events, then publishes them to `cloud/#`. Receives Cloud commands on `cloud/+/+/cmd/upload` and republishes them down to the Extreme-Edge on `edge/+/+/cmd/upload`. It is also responsible for uploading the requested images to the Cloud Object Storage via HTTP POST.

### Cloud

- **MQTT Broker (Mosquitto) [ENDPOINT]**: Central broker receiving bridged messages from Edge nodes. Configured to accept bridge connections from Edge brokers.
- **SQL Database (PostgreSQL)**: Central persistence for all events and metadata. Stores data according to the `edge_device`, `camera`, `dataset_store`, and `animal_detected` schema.
- **Object Storage (RustFS) [ENDPOINT]**: Central storage for all captured images.
- **Cloud Processing Service**: Ingests cloud messages (`cloud/#`), saves events centrally on the DB, and issues upload commands back to the Edge via `cloud/{edge_id}/{camera_id}/cmd/upload`. Exposes an HTTP endpoint to allow the Dashboard to retrieve images (fetching them from the Cloud Object Storage or requesting them from the Edge).
- **Dashboard [ENDPOINT]**: A blackbox module provided by ItalTel (not Grafana) for data visualization and system monitoring.

## BIM

- Mosquitto: [DockerHub](https://hub.docker.com/_/eclipse-mosquitto)
- PostgreSQL: [DockerHub](https://hub.docker.com/_/postgres)
- RustFS: [DockerHub](https://hub.docker.com/r/rustfs/rustfs)
  - RustFS is used due to MinIO deprecation.
