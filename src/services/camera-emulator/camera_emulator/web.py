"""FastAPI application – HTTP dashboard for the camera emulator."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests as http_requests
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from camera_emulator.config import Config
from camera_emulator.mqtt_client import MQTTClient

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Shared state – filled from main.py before startup
_cfg: Config
_mqtt: MQTTClient
_scenes: list[dict[str, Any]] = []
_scenes_dir: Path | None = None
_event_log: deque[dict[str, Any]] = deque(maxlen=200)
_event_scene_map: dict[str, int] = {}  # event_id → scene index


def init(
    cfg: Config,
    mqtt_client: MQTTClient,
    scenes: list[dict[str, Any]],
    scenes_dir: Path | None = None,
) -> None:
    """Wire up shared state before the app starts."""
    global _cfg, _mqtt, _scenes, _scenes_dir  # pylint: disable=global-statement
    _cfg = cfg
    _mqtt = mqtt_client
    _scenes = scenes
    _scenes_dir = scenes_dir

    # Register a callback so incoming commands appear in the log
    _mqtt.on_command(_on_incoming_command)

    # Register structured log callback for SYSTEM events (connect/disconnect/subscribe/LWT)
    _mqtt.on_log_event(_on_mqtt_log_event)


app = FastAPI(title="Camera Emulator Dashboard")


# --------------------------------------------------------------------------- #
#  Health check
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check."""
    return {
        "status": "ok",
        "mqtt_connected": str(_mqtt.connected),
    }


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _log_event(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    direction: str,
    topic: str,
    payload: dict,
    operation_type: str = "",
    trigger_reason: str = "",
    qos: int | None = None,
    retain: bool | None = None,
) -> None:
    """Append a structured entry to the in-memory event log."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dir": direction,
        "topic": topic,
        "payload": payload,
        "operation_type": operation_type,
        "trigger_reason": trigger_reason,
        "qos": qos,
        "retain": retain,
    }
    _event_log.appendleft(entry)


def _scene_index_from_event_id(event_id: str) -> int | None:
    """Look up the scene index for an event from the in-memory mapping."""
    return _event_scene_map.get(event_id)


def _do_photo_upload(event_id: str, upload_url: str, trigger: str) -> None:
    """Upload the photo for *event_id* to *upload_url* via HTTP PUT.

    Runs in a background thread so the MQTT callback isn't blocked.
    """
    scene_idx = _scene_index_from_event_id(event_id)
    if scene_idx is None or scene_idx < 0 or scene_idx >= len(_scenes):
        log.warning("Cannot resolve scene for event_id=%s", event_id)
        _log_event(
            "LOCAL",
            upload_url,
            {"event_id": event_id, "error": "Unknown scene index"},
            "UPLOAD_FAIL",
            trigger,
        )
        return

    scene = _scenes[scene_idx]
    photo_name = scene.get("photo")
    if not photo_name or _scenes_dir is None:
        log.warning("No photo configured for scene #%d", scene_idx + 1)
        _log_event(
            "LOCAL",
            upload_url,
            {"event_id": event_id, "error": "No photo file"},
            "UPLOAD_FAIL",
            trigger,
        )
        return

    photo_path = _scenes_dir / photo_name
    if not photo_path.is_file():
        log.warning("Photo file %s does not exist", photo_path)
        _log_event(
            "LOCAL",
            upload_url,
            {"event_id": event_id, "error": f"File not found: {photo_name}"},
            "UPLOAD_FAIL",
            trigger,
        )
        return

    log.info(
        "Uploading photo %s for event %s → %s",
        photo_name,
        event_id,
        upload_url,
    )
    _log_event(
        "LOCAL",
        upload_url,
        {"event_id": event_id, "photo": photo_name, "status": "UPLOADING"},
        "UPLOAD_START",
        trigger,
    )

    try:
        with photo_path.open("rb") as f:
            resp = http_requests.put(
                upload_url,
                data=f,
                headers={"Content-Type": "image/jpeg"},
                timeout=30,
            )
        resp.raise_for_status()
        log.info(
            "Upload SUCCESS for %s → %s (HTTP %d)",
            event_id,
            upload_url,
            resp.status_code,
        )
        _log_event(
            "LOCAL",
            upload_url,
            {
                "event_id": event_id,
                "photo": photo_name,
                "status": "SUCCESS",
                "http_code": resp.status_code,
            },
            "UPLOAD_DONE",
            trigger,
        )
        # Publish upload_status SUCCESS via MQTT
        _mqtt.publish_upload_status(
            {
                "event_id": event_id,
                "status": "SUCCESS",
                "remote_path": upload_url,
            },
            trigger=f"Auto: photo uploaded for {event_id}",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.exception("Upload FAILED for %s → %s", event_id, upload_url)
        _log_event(
            "LOCAL",
            upload_url,
            {
                "event_id": event_id,
                "photo": photo_name,
                "status": "ERROR",
                "error": str(exc),
            },
            "UPLOAD_FAIL",
            trigger,
        )
        _mqtt.publish_upload_status(
            {
                "event_id": event_id,
                "status": "ERROR",
                "message": str(exc),
            },
            trigger=f"Auto: upload failed for {event_id}",
        )


def _on_incoming_command(_topic: str, _payload: dict) -> None:
    """Handle incoming cmd/upload: upload the photo in a background thread."""
    event_id = _payload.get("event_id", "")
    upload_url = _payload.get("upload_url", "")
    if not event_id or not upload_url:
        log.warning("cmd/upload missing event_id or upload_url: %s", _payload)
        return
    threading.Thread(
        target=_do_photo_upload,
        args=(event_id, upload_url, f"MQTT cmd/upload: {event_id}"),
        daemon=True,
    ).start()


def _on_mqtt_log_event(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    direction: str,
    topic: str,
    payload: dict,
    operation_type: str,
    trigger_reason: str,
    qos: int | None,
    retain: bool | None,
) -> None:
    """Forward MQTT-layer events into the dashboard log."""
    _log_event(direction, topic, payload, operation_type, trigger_reason, qos, retain)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "cfg": _cfg,
            "connected": _mqtt.connected,
            "scenes": _scenes,
            "log": list(_event_log),
        },
    )


@app.get("/photos/{filename}")
async def serve_photo(filename: str):
    """Serve a scene photo from the scenes directory."""
    if _scenes_dir is None:
        return {"error": "No scenes directory configured"}
    # Sanitise: only allow plain filenames (no path traversal)
    safe = Path(filename).name
    photo_path = _scenes_dir / safe
    if not photo_path.is_file():
        return {"error": f"Photo {safe} not found"}
    return FileResponse(photo_path)


# --------------------------------------------------------------------------- #
#  API – lifecycle actions
# --------------------------------------------------------------------------- #


@app.post("/api/birth")
async def send_birth(request: Request):
    """Publish a birth/registration message."""
    body = await request.json()
    payload = {
        "edge_name": body.get("edge_name", "EMULATED_EDGE"),
        "edge_location": body.get("edge_location", "POINT(43.76794, 10.324979)"),
        "camera_type": body.get("camera_type", "BOAR_CAMERA_V3"),
        "camera_coords": body.get("camera_coords", "POINT(43.76797, 10.324982)"),
        "elevation": body.get("elevation", 30),
        "technical_params_json": body.get(
            "technical_params_json", {"iso": 800, "res": "2160x3840"}
        ),
    }
    _mqtt.publish_birth(payload, trigger="Manual: /api/birth")
    return {"status": "ok", "payload": payload}


@app.post("/api/telemetry")
async def send_telemetry(request: Request):
    """Publish a telemetry heartbeat."""
    body = await request.json()
    payload = {
        "timestamp": _now_iso(),
        "status": body.get("status", "Online"),
        "temperature": body.get("temperature", 20.0),
        "battery_level": body.get("battery_level", 100),
    }
    _mqtt.publish_telemetry(payload, trigger="Manual: /api/telemetry")
    return {"status": "ok", "payload": payload}


@app.post("/api/event")
async def send_event(request: Request):
    """Fire an event detection (from a scene or custom payload)."""
    body = await request.json()

    # If a scene index is provided, use that scene's data
    scene_idx = body.get("scene_index")
    if scene_idx is not None and 0 <= scene_idx < len(_scenes):
        scene = _scenes[scene_idx]
    else:
        scene = body

    # Event ID: UUID v4
    scene_num = (
        (scene_idx + 1)
        if (scene_idx is not None and 0 <= scene_idx < len(_scenes))
        else 0
    )
    event_id = str(uuid.uuid4())

    # Track event→scene mapping for photo upload resolution
    if scene_idx is not None and 0 <= scene_idx < len(_scenes):
        _event_scene_map[event_id] = scene_idx

    payload = {
        "event_id": event_id,
        "capture_time": _now_iso(),
        "count": scene.get("count", len(scene.get("detections", []))),
        "detections": scene.get("detections", []),
    }
    trigger = (
        f"Scene #{scene_num} ({scene.get('name', 'unnamed')})"
        if scene_idx is not None and 0 <= scene_idx < len(_scenes)
        else "Custom event via /api/event"
    )
    _mqtt.publish_event(payload, trigger=trigger)
    return {"status": "ok", "payload": payload}


@app.post("/api/upload_status")
async def send_upload_status(request: Request):
    """Report upload success or failure for an event."""
    body = await request.json()
    event_id = body.get("event_id", str(uuid.uuid4()))
    success = body.get("success", True)
    if success:
        payload = {
            "event_id": event_id,
            "status": "SUCCESS",
            "remote_path": body.get(
                "remote_path",
                f"http://object-storage-s3.edge/bucket/{event_id.lower()}.jpg",
            ),
        }
    else:
        payload = {
            "event_id": event_id,
            "status": "ERROR",
            "message": body.get("message", "Emulated upload error"),
        }
    status_label = "SUCCESS" if success else "ERROR"
    _mqtt.publish_upload_status(
        payload, trigger=f"Manual: /api/upload_status ({status_label})"
    )
    return {"status": "ok", "payload": payload}


@app.post("/api/emulate_upload_cmd")
async def emulate_upload_cmd(request: Request):
    """Simulate receiving an MQTT cmd/upload command."""
    body = await request.json()
    event_id = body.get("event_id", "")
    upload_url = body.get("upload_url", "")
    if not event_id or not upload_url:
        return {"status": "error", "detail": "event_id and upload_url are required"}

    # Log the emulated incoming command in the dashboard
    _log_event(
        "IN",
        f"{_cfg.topic_prefix()}/cmd/upload",
        {"event_id": event_id, "upload_url": upload_url},
        "RECEIVED",
        "Emulated: /api/emulate_upload_cmd",
        qos=1,
        retain=False,
    )
    log.info("Emulated cmd/upload for %s → %s", event_id, upload_url)

    # Trigger upload in background (same path as real MQTT command)
    threading.Thread(
        target=_do_photo_upload,
        args=(event_id, upload_url, f"Emulated cmd/upload: {event_id}"),
        daemon=True,
    ).start()
    return {"status": "ok", "event_id": event_id, "upload_url": upload_url}


@app.post("/api/disconnect")
async def graceful_disconnect():
    """Publish an offline telemetry then disconnect."""
    payload = {"timestamp": _now_iso(), "status": "Offline"}
    _mqtt.publish_telemetry(payload, trigger="Manual: /api/disconnect (offline)")
    _mqtt.stop()
    return {"status": "ok", "detail": "Disconnected gracefully (offline published)."}


@app.post("/api/reconnect")
async def reconnect():
    """Reconnect to the MQTT broker."""
    try:
        _mqtt.start(trigger="Manual: /api/reconnect")
        return {"status": "ok", "detail": "Reconnecting…"}
    except OSError as exc:
        return {"status": "error", "detail": str(exc)}


# --------------------------------------------------------------------------- #
#  API – read-only state
# --------------------------------------------------------------------------- #


@app.get("/api/log")
async def get_log():
    """Return the recent message log."""
    return list(_event_log)


@app.get("/api/status")
async def get_status():
    """Return current connection status and identifiers."""
    return {
        "connected": _mqtt.connected,
        "edge_id": _cfg.edge_id,
        "camera_id": _cfg.camera_id,
        "broker": f"{_cfg.mqtt_host}:{_cfg.mqtt_port}",
    }
