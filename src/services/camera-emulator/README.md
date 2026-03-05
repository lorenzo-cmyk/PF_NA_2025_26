# Camera Emulator

A Python service that emulates a gBOAR extreme-edge camera trap.  
It connects to an MQTT broker and exposes a web dashboard to manually trigger every lifecycle message the real camera would produce.

## Quick start

```bash
# Install (uv)
uv sync

# Run (broker must be reachable)
uv run camera-emulator
```

The dashboard is served at **<http://localhost:8080>** by default.

## Environment variables

| Variable         | Default                   | Description                        |
| ---------------- | ------------------------- | ---------------------------------- |
| `MQTT_HOST`      | `localhost`               | MQTT broker hostname               |
| `MQTT_PORT`      | `1883`                    | MQTT broker port                   |
| `MQTT_USERNAME`  | *(none)*                  | Optional broker username           |
| `MQTT_PASSWORD`  | *(none)*                  | Optional broker password           |
| `MQTT_CLIENT_ID` | `camera-emulator`         | MQTT client identifier             |
| `EDGE_ID`        | `edge_01`                 | Edge device identifier             |
| `CAMERA_ID`      | `cam_01`                  | Camera identifier                  |
| `WEB_HOST`       | `0.0.0.0`                 | Dashboard listen address           |
| `WEB_PORT`       | `8080`                    | Dashboard listen port              |
| `SCENES_FILE`    | `demo_scenes/scenes.json` | Path to the scenes definition file |

## MQTT messages emulated

| Action          | Topic                                            | QoS | Retained |
| --------------- | ------------------------------------------------ | --- | -------- |
| Birth           | `edge/{edge_id}/{camera_id}/lifecycle/birth`     | 1   | Yes      |
| Telemetry / LWT | `edge/{edge_id}/{camera_id}/telemetry`           | 1   | Yes      |
| Event Detection | `edge/{edge_id}/{camera_id}/event`               | 1   | No       |
| Upload Status   | `edge/{edge_id}/{camera_id}/event/upload_status` | 1   | No       |

The emulator also **subscribes** to `edge/{edge_id}/{camera_id}/cmd/upload` to receive upload commands from the Edge Processing Service.

## Scenes

Scenes are predefined event payloads stored in `demo_scenes/scenes.json`.  
Each scene has a `name`, `description`, detection list, and a `photo` field pointing to a JPEG file in the same directory.

## Dashboard features

- **Birth**: register the camera on the broker (retained)
- **Telemetry**: send heartbeats with status / temperature / battery
- **Event Detection**: fire a scene or a custom detection payload
- **Upload Status**: report success or failure for an event upload
- **Connection Control**: graceful disconnect (publishes offline) or reconnect
- **Message Log**: live view of all published and received messages
