# WatchEdge Camera Service

Edge service that runs real-time wildlife detection on a camera feed and reports events to the rest of the WatchEdge platform via MQTT.  A built-in web UI lets operators monitor the stream and control the service without SSH access.

## Features

- **YOLOv9t ONNX inference** — detects Wild Boar, Wolf, and Deer at a configurable frame rate.
- **Flexible video source** — live USB camera or any pre-recorded `.mp4`/`.avi` file in `samples/videos/`.
- **MQTT integration** — publishes retained birth/telemetry messages and QoS-1 detection events; subscribes to upload commands.
- **Event throttling** — prevents MQTT flooding with a configurable cooldown window.
- **JPEG snapshot** — saves an annotated frame for every emitted event under `data/images/`.
- **Web UI** — MJPEG live stream, MQTT event log, and a configuration/control panel at `http://<host>:8080`.
- **REST API** — programmatic control over the video source, MQTT connection, and manual event injection.

## Architecture

```text
VideoSource ──► InferenceEngine ──► EventPipeline ──► MQTTClient
                     │                    │
              (annotated frame)     (JPEG saved to
                     │               data/images/)
                     ▼
                  WebUI (MJPEG stream + event log)
```

| Module                | Responsibility                                                  |
| --------------------- | --------------------------------------------------------------- |
| `config.py`           | Loads and validates all settings from `.env` / environment      |
| `video_source.py`     | Thread-safe abstraction over USB camera or video file           |
| `detector.py`         | YOLOv9t ONNX pre/post-processing; distance & size heuristics    |
| `inference_engine.py` | Background thread that drives `Detector` at `INFERENCE_FPS`     |
| `event_pipeline.py`   | Throttles detections, builds MQTT payloads, saves frames        |
| `mqtt_client.py`      | Birth, telemetry, event publishing; upload-command subscription |
| `web.py`              | FastAPI app with Jinja2 templates and MJPEG stream              |
| `api.py`              | REST control endpoints mounted on the FastAPI app               |

## MQTT Topics

All topics are prefixed with `edge/<EDGE_ID>/<CAMERA_ID>`.

| Topic (relative)      | Direction | QoS | Retained | Description                                       |
| --------------------- | --------- | --- | -------- | ------------------------------------------------- |
| `lifecycle/birth`     | OUT       | 1   | yes      | Camera registration payload                       |
| `telemetry`           | OUT       | 1   | yes      | Periodic heartbeat (status, temperature, battery) |
| `event`               | OUT       | 1   | no       | Detection event with animal list                  |
| `event/upload_status` | OUT       | 1   | no       | Result of a broker-requested upload               |
| `cmd/upload`          | IN        | —   | —        | Trigger an image upload                           |

### Detection event payload

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "capture_time": "2026-03-11T10:00:00Z",
  "count": 2,
  "detections": [
    {
      "animal_type": "boar",
      "confidence": 0.96,
      "distance": 39.7,
      "size_estimate": 1.2
    }
  ]
}
```

## Configuration

Settings are read from a `.env` file in the project root (or from environment variables).

| Variable                      | Default                         | Description                                 |
| ----------------------------- | ------------------------------- | ------------------------------------------- |
| `EDGE_ID`                     | **required**                    | UUID identifying the edge node              |
| `CAMERA_ID`                   | **required**                    | UUID identifying this camera                |
| `MQTT_HOST`                   | `localhost`                     | MQTT broker hostname                        |
| `MQTT_PORT`                   | `1883`                          | MQTT broker port                            |
| `MQTT_USERNAME`               | _(none)_                        | Broker username                             |
| `MQTT_PASSWORD`               | _(none)_                        | Broker password                             |
| `MQTT_CLIENT_ID`              | _(auto)_                        | MQTT client ID (auto-generated if empty)    |
| `WEB_HOST`                    | `0.0.0.0`                       | Web server bind address                     |
| `WEB_PORT`                    | `8080`                          | Web server port                             |
| `MODEL_PATH`                  | `model/best_yolov9t_aug.onnx`   | Path to the ONNX model                      |
| `CONFIDENCE_THRESHOLD`        | `0.6`                           | Minimum detection confidence                |
| `IOU_THRESHOLD`               | `0.5`                           | NMS IoU threshold                           |
| `INFERENCE_FPS`               | `5`                             | Detection frames per second                 |
| `DEFAULT_SOURCE`              | `video`                         | Initial source: `usb` or `video`            |
| `USB_CAMERA_INDEX`            | `0`                             | OpenCV device index for the USB camera      |
| `SAMPLES_DIR`                 | `samples/`                      | Directory containing sample videos          |
| `SCENES_FILE`                 | `samples/scenes.json`           | Pre-defined demo scenes for event injection |
| `EVENT_THROTTLE_S`            | `1.0`                           | Minimum seconds between emitted events      |
| `IMAGE_DIR`                   | `data/images/`                  | Where annotated JPEG snapshots are saved    |
| `TELEMETRY_INTERVAL_S`        | `30.0`                          | Heartbeat publish interval                  |
| `BIRTH_EDGE_NAME`             | `SAN_ROSSORE_PARK`              | Edge node display name                      |
| `BIRTH_EDGE_LOCATION`         | `San Rossore Park (PI, Italy)`  | Human-readable location                     |
| `BIRTH_CAMERA_TYPE`           | `EXTREME_EDGE_CAMERA_V8`        | Camera model identifier                     |
| `BIRTH_CAMERA_COORDS`         | `POINT(43.7233401, 10.3365951)` | WKT geographic coordinates                  |
| `BIRTH_ELEVATION`             | `20`                            | Installation height in metres               |
| `BIRTH_TECHNICAL_PARAMS_JSON` | `{"res": "2568x1724"}`          | Arbitrary JSON technical metadata           |

Minimal `.env` example:

```dotenv
EDGE_ID=11111111-1111-1111-1111-111111111111
CAMERA_ID=22222222-2222-2222-2222-222222222222
MQTT_HOST=mqtt.example.com
```

## Running

Tailwind CSS is downloaded automatically on the first boot of the camera service and cached locally under `templates/static/`.
If needed, it can also be downloaded ahead of time by running `camera/tailwind.py` manually before startup.

### Local (development)

```bash
# Install dependencies (Python 3.14.3+)
# Use optional extras depending on your hardware: '--all-extras' for the standard cpu
# OR '--extra nvidia-gpu' (modern CuDNN 9) OR '--extra nvidia-gpu-pascal' (older CuDNN 8/earlier 9 pins)
uv sync --extra cpu

# Create .env with at least EDGE_ID and CAMERA_ID
cp .env.example .env   # or write it manually

uv run camera          # via the project script
# or
uv run python main.py
```

### Docker

You can build the Docker image with different dependencies using the `RUNTIME_ENV` build argument (options: `cpu`, `nvidia-gpu`, `nvidia-gpu-pascal`). This ensures the container only contains the packages relevant to your execution environment.

```bash
docker build --build-arg RUNTIME_ENV=cpu -t watchedge-camera .

docker run --rm \
  -e EDGE_ID=11111111-1111-1111-1111-111111111111 \
  -e CAMERA_ID=22222222-2222-2222-2222-222222222222 \
  -e MQTT_HOST=mqtt.example.com \
  -p 8080:8080 \
  watchedge-camera
```

Mount `data/` as a volume to persist event snapshots:

```bash
docker run --rm \
  -e EDGE_ID=... -e CAMERA_ID=... -e MQTT_HOST=... \
  -p 8080:8080 \
  -v "$(pwd)/data:/app/data" \
  watchedge-camera
```

## REST API

All endpoints are served by the same FastAPI app as the Web UI.

| Method | Path                   | Description                                                       |
| ------ | ---------------------- | ----------------------------------------------------------------- |
| `GET`  | `/health`              | Returns MQTT, inference, and source status                        |
| `POST` | `/api/restart`         | Restarts the inference engine and MQTT client                     |
| `POST` | `/api/mqtt/disconnect` | Disconnects from the broker                                       |
| `POST` | `/api/mqtt/reconnect`  | Reconnects to the broker                                          |
| `POST` | `/api/source/switch`   | Switch source (`{"source": "usb"\|"video", "video_name": "..."}`) |
| `POST` | `/api/source/pause`    | Pause video playback                                              |
| `POST` | `/api/source/resume`   | Resume video playback                                             |
| `POST` | `/api/source/seek`     | Seek to timestamp (`{"timestamp_ms": 0}`)                         |
| `POST` | `/api/event/inject`    | Publish a detection event (scene name or raw payload)             |
| `POST` | `/api/birth`           | Manually publish the birth/registration message                   |
| `POST` | `/api/telemetry`       | Manually publish a telemetry message                              |

Interactive API docs are available at `http://<host>:8080/docs`.
