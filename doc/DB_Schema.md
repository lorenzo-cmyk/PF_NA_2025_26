# WatchEdge – Database Schema Specification

> Database: **watchedge-db** · User: **watchedge** · Extensions: `uuid-ossp`, `postgis`

## 1. Table: `edge_device`

_Top-level entity representing the physical computing nodes._

| Field Name    | Data Type | Key    | Constraints       | Comments                         |
| :------------ | :-------- | :----- | :---------------- | :------------------------------- |
| **`edge_id`** | `UUID`    | **PK** | DEFAULT `uuid_generate_v4()` | Auto-generated unique identifier. |
| `name`        | `TEXT`    |        | `NOT NULL`        | Human-readable name.             |
| `location`    | `TEXT`    |        |                   | Descriptive location string.     |

## 2. Table: `camera`

_Represents imaging hardware. Child of `edge_device`._

| Field Name              | Data Type                | Key    | Constraints                          | Comments                              |
| :---------------------- | :----------------------- | :----- | :----------------------------------- | :------------------------------------ |
| **`camera_id`**         | `UUID`                   | **PK** | DEFAULT `uuid_generate_v4()`         | Auto-generated unique identifier.     |
| `edge_id`               | `UUID`                   | **FK** | `NOT NULL`, `ON DELETE RESTRICT`     | References `edge_device.edge_id`.     |
| `type`                  | `TEXT`                   |        |                                      | Camera model or hardware type.        |
| `location_coordinates`  | `GEOGRAPHY(Point, 4326)` |        |                                      | PostGIS geographic coordinates.       |
| `technical_params_json` | `JSONB`                  |        | DEFAULT `'{}'::jsonb`                | Configuration parameters (resolution, etc.). |
| `elevation`             | `DECIMAL(8,2)`           |        |                                      | Height of installation (meters).      |
| `status`                | `camera_status` (ENUM)   |        | `NOT NULL`, DEFAULT `'Offline'`      | `'Online'` or `'Offline'`.            |
| `temperature`           | `DECIMAL(5,2)`           |        |                                      | Ambient or internal temperature.      |
| `battery_level`         | `DECIMAL(5,2)`           |        | `CHECK (0..100)`                     | Battery percentage.                   |

## 3. Table: `datasetstore`

_Represents a captured image event. Child of `camera`._

| Field Name     | Data Type                      | Key    | Constraints                      | Comments                            |
| :------------- | :----------------------------- | :----- | :------------------------------- | :---------------------------------- |
| **`event_id`** | `UUID`                         | **PK** | DEFAULT `uuid_generate_v4()`     | Auto-generated unique identifier.   |
| `camera_id`    | `UUID`                         | **FK** | `NOT NULL`, `ON DELETE CASCADE`  | References `camera.camera_id`.      |
| `time`         | `TIMESTAMP WITH TIME ZONE`     |        | `NOT NULL`, DEFAULT `now()`      | Capture timestamp.                  |
| `count`        | `INT`                          |        | `NOT NULL`, DEFAULT `0`          | Number of detections (trigger-maintained). |
| `imagepath`    | `TEXT`                         |        | `NOT NULL`                       | Full URL to the image in object storage.   |

## 4. Table: `animaldetected`

_Represents specific AI inference results. Child of `datasetstore`._

| Field Name       | Data Type      | Key    | Constraints                     | Comments                                  |
| :--------------- | :------------- | :----- | :------------------------------ | :---------------------------------------- |
| **`detection_id`** | `UUID`       | **PK** | DEFAULT `uuid_generate_v4()`    | Auto-generated unique identifier.         |
| `event_id`       | `UUID`         | **FK** | `NOT NULL`, `ON DELETE CASCADE` | References `datasetstore.event_id`.       |
| `animal_type`    | `TEXT`         |        |                                 | Class of the detected animal.             |
| `distance`       | `DECIMAL(6,2)` |        |                                 | Estimated distance from camera (meters).  |
| `size_estimate`  | `DECIMAL(6,2)` |        |                                 | Approximate body size (meters).           |
| `confidence`     | `DECIMAL(4,3)` |        | `CHECK (0..1)`                  | AI confidence score.                      |

## Indexes

| Index                       | Table            | Column      |
| :-------------------------- | :--------------- | :---------- |
| `idx_datasetstore_camera`   | `datasetstore`   | `camera_id` |
| `idx_animaldetected_event`  | `animaldetected` | `event_id`  |

## Trigger

`trg_refresh_count` — fires `AFTER INSERT OR DELETE` on `animaldetected`.
Calls `refresh_event_count()` to keep `datasetstore.count` in sync with the
actual number of child detection rows.

## Relationship Overview

1. **`edge_device`** — 1:N → **`camera`**
2. **`camera`** — 1:N → **`datasetstore`**
3. **`datasetstore`** — 1:N → **`animaldetected`**
