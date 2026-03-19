"""WebAPI: control and configuration REST endpoints mounted on the WebUI app."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from camera.config import Config
from camera.event_pipeline import EventPipeline
from camera.inference_engine import InferenceEngine
from camera.mqtt_client import MQTTClient
from camera.video_source import VideoSource

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WebAPI:
    """Owns the APIRouter with all control/configuration endpoints."""

    def __init__(
        self,
        inference_engine: InferenceEngine,
        mqtt: MQTTClient,
        video_source: VideoSource,
        event_pipeline: EventPipeline,
        cfg: Config,
        scenes: list[dict[str, Any]],
    ) -> None:
        self._engine = inference_engine
        self._mqtt = mqtt
        self._video = video_source
        self._pipeline = event_pipeline
        self._cfg = cfg
        self._scenes = scenes

        self.router = APIRouter()
        self._register_routes()

    # -- route registration ------------------------------------------------ #

    def _register_routes(self) -> None:
        r = self.router

        # Health
        @r.get("/health")
        def health():
            info = self._video.get_video_info()
            return {
                "mqtt_connected": self._mqtt.connected,
                "inference_running": self._engine.running,
                "execution_provider": self._engine.execution_provider,
                "source_type": info.get("source_type"),
            }

        # Software restart
        @r.post("/api/restart")
        def restart():
            try:
                self._engine.stop()
                self._mqtt.stop()
                self._mqtt.start(trigger="Manual: restart")
                self._engine.start()
                return {"success": True}
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log.exception("Restart failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        # MQTT connection management
        @r.post("/api/mqtt/disconnect")
        def mqtt_disconnect():
            try:
                self._mqtt.stop()
                return {"success": True}
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        @r.post("/api/mqtt/reconnect")
        def mqtt_reconnect():
            try:
                self._mqtt.start(trigger="Manual: reconnect")
                return {"success": True}
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Video source control
        @r.post("/api/source/switch")
        async def source_switch(request: Request):
            body = await request.json()
            source = body.get("source", "usb")
            video_name = body.get("video_name")
            if source not in ("usb", "video"):
                raise HTTPException(
                    status_code=400, detail="source must be 'usb' or 'video'"
                )
            self._video.switch(source, video_name)
            return {"success": True, "source": source}

        @r.post("/api/source/pause")
        def source_pause():
            self._video.pause()
            return {"success": True}

        @r.post("/api/source/resume")
        def source_resume():
            self._video.resume()
            return {"success": True}

        @r.post("/api/source/seek")
        async def source_seek(request: Request):
            body = await request.json()
            ts_ms = body.get("timestamp_ms")
            if ts_ms is None:
                raise HTTPException(status_code=400, detail="timestamp_ms is required")
            self._video.seek(float(ts_ms))
            return {"success": True}

        @r.get("/api/source/info")
        def source_info():
            return self._video.get_video_info()

        @r.get("/api/source/videos")
        def source_videos():
            return self._video.list_videos()

        # Scenes
        @r.get("/api/scenes")
        def scenes():
            return self._scenes

        # Event injection
        @r.post("/api/event/inject")
        async def event_inject(request: Request):
            body = await request.json()
            scene_index = body.get("scene_index")

            if scene_index is not None:
                if not (0 <= scene_index < len(self._scenes)):
                    raise HTTPException(status_code=400, detail="Invalid scene_index")
                scene = self._scenes[scene_index]
                payload: dict[str, Any] = {
                    "event_id": str(uuid.uuid4()),
                    "capture_time": _ts(),
                    "count": scene.get("count", len(scene.get("detections", []))),
                    "detections": scene.get("detections", []),
                }
            else:
                # Custom payload provided directly
                event_id = body.get("event_id") or str(uuid.uuid4())
                payload = {
                    "event_id": event_id,
                    "capture_time": body.get("capture_time") or _ts(),
                    "count": body.get("count", 0),
                    "detections": body.get("detections", []),
                }

            self._mqtt.publish_event(payload, trigger="Manual: event inject")
            return {"success": True, "event_id": payload["event_id"]}

        # Manual birth / telemetry
        @r.post("/api/birth")
        async def send_birth(request: Request):
            import json as _json

            body = await request.json()
            try:
                tech = _json.loads(body.get("technical_params_json", "{}"))
            except ValueError, TypeError:
                tech = {}
            payload = {
                "edge_name": body.get("edge_name", self._cfg.birth_edge_name),
                "edge_location": body.get(
                    "edge_location", self._cfg.birth_edge_location
                ),
                "camera_type": body.get("camera_type", self._cfg.birth_camera_type),
                "camera_coords": body.get(
                    "camera_coords", self._cfg.birth_camera_coords
                ),
                "elevation": body.get("elevation", self._cfg.birth_elevation),
                "technical_params_json": tech,
            }
            self._mqtt.publish_birth(payload=payload, trigger="Manual: birth")
            return {"success": True}

        @r.post("/api/telemetry")
        async def send_telemetry(request: Request):
            body = await request.json()
            payload = {
                "timestamp": body.get("timestamp") or _ts(),
                "status": body.get("status", "Online"),
                "temperature": body.get("temperature", 0.0),
                "battery_level": body.get("battery_level", 100),
            }
            self._mqtt.publish_telemetry(payload=payload, trigger="Manual: telemetry")
            return {"success": True}
