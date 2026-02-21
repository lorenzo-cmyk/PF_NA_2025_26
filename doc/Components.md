# gBOAR - System Components & Architecture

## Architecture Diagram

```text
+---------------------------------------------------------+
|                     EXTREME-EDGE                        |
|                                                         |
|  +---------------------------------------------------+  |
|  | Camera Management System & AI Detection Software  |  |
|  +---------------------------------------------------+  |
|                           |                             |
|  +---------------------------------------------------+  |
|  | gBOAR Library (Python MQTT Client)                |  |
|  +---------------------------------------------------+  |
+---------------------------+-----------------------------+
                            |
                            | MQTT (edge/#)
                            v
+---------------------------------------------------------+
|                         EDGE                            |
|                                                         |
|  +-----------------------+   +-----------------------+  |
|  | MQTT Broker           |   | Object Storage        |  |
|  | (Mosquitto)           |   | (RustFS)              |  |
|  | [MUST EXPOSE PORT]    |   | [MUST EXPOSE PORT]    |  |
|  +-----------+-----------+   +-----------------------+  |
|              |                                          |
|  +-----------v-----------+   +-----------------------+  |
|  | Edge Processing       |   | SQL Database          |  |
|  | Service               +---> (PostgreSQL)          |  |
|  +-----------------------+   +-----------------------+  |
+---------------------------+-----------------------------+
                            |
                            | MQTT Bridge (cloud/#)
                            v
+---------------------------------------------------------+
|                         CLOUD                           |
|                                                         |
|  +-----------------------+   +-----------------------+  |
|  | MQTT Broker           |   | Object Storage        |  |
|  | (Mosquitto)           |   | (RustFS)              |  |
|  | [MUST EXPOSE PORT]    |   | [MUST EXPOSE PORT]    |  |
|  +-----------+-----------+   +-----------------------+  |
|              |                                          |
|  +-----------v-----------+   +-----------------------+  |
|  | Cloud Processing      |   | SQL Database          |  |
|  | Service               +---> (PostgreSQL)          |  |
|  +-----------+-----------+   +-----------------------+  |
|              |                                          |
|              | HTTP                                     |
|  +-----------v---------------------------------------+  |
|  | Dashboard (ItalTel Blackbox)                      |  |
|  | [MUST EXPOSE PORT]                                |  |
|  +---------------------------------------------------+  |
+---------------------------------------------------------+
```

## Component Breakdown

### Extreme-Edge

- **Camera Management System & AI Detection Software**: Handles image capture and local AI inference.
- **gBOAR Library**: Python library enabling the CMS to communicate with the network via MQTT. Publishes lifecycle (`birth`), `telemetry` (with LWT configured), and `event` data to the `edge/{edge_id}/{camera_id}/...` namespace. Accepts commands on `edge/{edge_id}/{camera_id}/cmd/upload` to upload files using HTTP POST to the Edge Object Storage.

### Edge

- **MQTT Broker (Mosquitto) [MUST EXPOSE PORT]**: Local broker for Extreme-Edge to Edge communication. Configured to bridge all `cloud/#` topics up to the Cloud MQTT Broker, and bridge `cloud/+/+/cmd/upload` commands from the Cloud down to the Edge without remapping. Manages queuing and mutual TLS autonomously.
- **SQL Database (PostgreSQL)**: Local persistence for events and metadata. Stores data according to the `edge_device`, `camera`, `dataset_store`, and `animal_detected` schema.
- **Object Storage (RustFS) [MUST EXPOSE PORT]**: Local storage for captured images.
- **Edge Processing Service**: Intermediary service maintaining exactly 1 active MQTT session to the local broker. Subscribes to `edge/#`, ingests, aggregates, validates, and enriches incoming events, then publishes them to `cloud/#`. Receives Cloud commands on `cloud/+/+/cmd/upload` and republishes them down to the Extreme-Edge on `edge/+/+/cmd/upload`.

### Cloud

- **MQTT Broker (Mosquitto) [MUST EXPOSE PORT]**: Central broker receiving bridged messages from Edge nodes. Configured to accept bridge connections from Edge brokers.
- **SQL Database (PostgreSQL)**: Central persistence for all events and metadata. Stores data according to the `edge_device`, `camera`, `dataset_store`, and `animal_detected` schema.
- **Object Storage (RustFS) [MUST EXPOSE PORT]**: Central storage for all captured images.
- **Cloud Processing Service**: Ingests cloud messages (`cloud/#`), saves events centrally on the DB, and issues upload commands back to the Edge via `cloud/{edge_id}/{camera_id}/cmd/upload`. Exposes an HTTP endpoint to allow the Dashboard to retrieve images (fetching them from the Cloud Object Storage or requesting them from the Edge).
- **Dashboard [MUST EXPOSE PORT]**: A blackbox module provided by ItalTel (not Grafana) for data visualization and system monitoring.
