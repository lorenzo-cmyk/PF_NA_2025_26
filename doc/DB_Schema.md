# gBOAR - Database Schema Specification

## 1. Table: `edge_device`

_Top-level entity representing the physical computing nodes._

| Field Name    | Data Type          | Key    | Comments                                                                          |
| :------------ | :----------------- | :----- | :-------------------------------------------------------------------------------- |
| **`edge_id`** | `VARCHAR` / `TEXT` | **PK** | Unique identifier for the edge node.                                              |
| `name`        | `VARCHAR`          |        | Human-readable name for the device.                                               |
| `location`    | `POINT` or `TEXT`  |        | Geographic location of the device (could be coordinates or a descriptive string). |

## 2. Table: `camera`

_Represents imaging hardware. Child of `edge_device`._

| Field Name              | Data Type          | Key    | Comments                                                                                  |
| :---------------------- | :----------------- | :----- | :---------------------------------------------------------------------------------------- |
| **`camera_id`**         | `VARCHAR` / `TEXT` | **PK** | Unique identifier for the camera.                                                         |
| `edge_id`               | `VARCHAR` / `TEXT` | **FK** | References `edge_device.edge_id`.                                                         |
| `type`                  | `VARCHAR`          |        | The model or hardware type of the camera.                                                 |
| `location_coordinates`  | `POINT`            |        | GPS coordinates of the camera sensor (PostgreSQL geometric type).                         |
| `technical_params_json` | `JSONB`            |        | Configuration parameters (resolution, etc.) stored in Binary JSON for efficient querying. |
| `elevation`             | `NUMERIC`          |        | Height of installation (in meters).                                                       |
| `status`                | `VARCHAR`          |        | Operational status (e.g., 'active', 'maintenance').                                       |
| `temperature`           | `NUMERIC`          |        | Telemetry: Internal or ambient temperature.                                               |
| `battery_level`         | `INTEGER`          |        | Telemetry: Battery percentage (0-100).                                                    |

## 3. Table: `dataset_store`

_Represents a captured image event. Child of `camera`._

| Field Name          | Data Type     | Key    | Comments                                                          |
| :------------------ | :------------ | :----- | :---------------------------------------------------------------- |
| **`event_id`**      | `VARCHAR`     | **PK** | Unique ID, typically a composite of Camera ID + Timestamp.        |
| `camera_id`         | `VARCHAR`     | **FK** | References `camera.camera_id`.                                    |
| `time`              | `TIMESTAMPTZ` |        | Timestamp of the capture (with Time Zone).                        |
| `count`             | `INTEGER`     |        | Total number of objects detected in this event.                   |
| `image_path`        | `TEXT`        |        | Local file system path to the raw image.                          |
| `event_coordinates` | `POINT`       |        | Specific location data associated with the event/detection frame. |

## 4. Table: `animal_detected`

_Represents specific AI inference results. Child of `dataset_store`._

| Field Name              | Data Type             | Key    | Comments                                                           |
| :---------------------- | :-------------------- | :----- | :----------------------------------------------------------------- |
| **`detection_id_uuid`** | `UUID`                | **PK** | Globally Unique Identifier. Generated via `uuid-ossp` extension.   |
| `event_id`              | `VARCHAR`             | **FK** | References `dataset_store.event_id`.                               |
| `animal_type`           | `VARCHAR`             |        | Class of the detected animal (e.g., 'deer', 'boar').               |
| `distance`              | `NUMERIC`             |        | Estimated distance from the camera (in meters).                    |
| `size_estimate`         | `VARCHAR` / `NUMERIC` |        | Approximate size (can be a bounding box area or categorical size). |
| `confidence`            | `NUMERIC`             |        | AI Confidence score (typically 0.0 to 1.0).                        |

## Relationship Overview

1. **`edge_device`** - 1:N - **`camera`**
2. **`camera`** - 1:N - **`dataset_store`**
3. **`dataset_store`** - 1:N - **`animal_detected`**
