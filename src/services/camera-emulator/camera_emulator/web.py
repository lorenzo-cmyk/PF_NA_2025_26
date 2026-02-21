"""FastAPI application – HTTP dashboard for the camera emulator."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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
_event_log: deque[dict[str, Any]] = deque(maxlen=200)


def init(cfg: Config, mqtt_client: MQTTClient, scenes: list[dict[str, Any]]) -> None:
    """Wire up shared state before the app starts."""
    global _cfg, _mqtt, _scenes  # pylint: disable=global-statement
    _cfg = cfg
    _mqtt = mqtt_client
    _scenes = scenes

    # Register a callback so incoming commands appear in the log
    _mqtt.on_command(_on_incoming_command)


app = FastAPI(title="Camera Emulator Dashboard")


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _log_event(direction: str, topic: str, payload: dict) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dir": direction,
        "topic": topic,
        "payload": payload,
    }
    _event_log.appendleft(entry)


def _on_incoming_command(topic: str, payload: dict) -> None:
    _log_event("IN", topic, payload)


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
    _mqtt.publish_birth(payload)
    _log_event("OUT", f"{_cfg.topic_prefix()}/lifecycle/birth", payload)
    return {"status": "ok", "payload": payload}


@app.post("/api/telemetry")
async def send_telemetry(request: Request):
    """Publish a telemetry heartbeat."""
    body = await request.json()
    payload = {
        "timestamp": _now_iso(),
        "status": body.get("status", "active"),
        "temperature": body.get("temperature", 20.0),
        "battery_level": body.get("battery_level", 100),
    }
    _mqtt.publish_telemetry(payload)
    _log_event("OUT", f"{_cfg.topic_prefix()}/telemetry", payload)
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

    event_id = f"EVT_{uuid.uuid4().hex[:12].upper()}"
    payload = {
        "event_id": event_id,
        "capture_time": _now_iso(),
        "count": scene.get("count", len(scene.get("detections", []))),
        "event_coordinates": scene.get(
            "event_coordinates", "POINT(43.76797, 10.324982)"
        ),
        "detections": scene.get("detections", []),
    }
    _mqtt.publish_event(payload)
    _log_event("OUT", f"{_cfg.topic_prefix()}/event", payload)
    return {"status": "ok", "payload": payload}


@app.post("/api/upload_status")
async def send_upload_status(request: Request):
    """Report upload success or failure for an event."""
    body = await request.json()
    event_id = body.get("event_id", f"EVT_{uuid.uuid4().hex[:12].upper()}")
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
    _mqtt.publish_upload_status(payload)
    _log_event("OUT", f"{_cfg.topic_prefix()}/event/upload_status", payload)
    return {"status": "ok", "payload": payload}


@app.post("/api/disconnect")
async def graceful_disconnect():
    """Publish an offline telemetry then disconnect."""
    payload = {"timestamp": _now_iso(), "status": "offline"}
    _mqtt.publish_telemetry(payload)
    _log_event("OUT", f"{_cfg.topic_prefix()}/telemetry", payload)
    _mqtt.stop()
    return {"status": "ok", "detail": "Disconnected gracefully (offline published)."}


@app.post("/api/reconnect")
async def reconnect():
    """Reconnect to the MQTT broker."""
    try:
        _mqtt.start()
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
