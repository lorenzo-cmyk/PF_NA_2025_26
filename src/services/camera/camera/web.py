"""FastAPI WebUI: homepage, configuration page, MJPEG stream, and status/log endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from camera.config import Config
from camera.inference_engine import InferenceEngine
from camera.mqtt_client import MQTTClient
from camera.video_source import VideoSource

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class WebUI:
    """Owns the FastAPI app, the MJPEG stream, and the presentation routes."""

    def __init__(
        self,
        cfg: Config,
        mqtt: MQTTClient,
        inference_engine: InferenceEngine,
        video_source: VideoSource,
    ) -> None:
        self._cfg = cfg
        self._mqtt = mqtt
        self._engine = inference_engine
        self._video = video_source
        self._stream_interval = 1.0 / cfg.inference_fps
        self._event_log: deque[dict[str, Any]] = deque(maxlen=200)

        self.app = FastAPI(title="WatchEdge Camera")
        self._register_routes()

    # -- log callback ------------------------------------------------------ #

    def append_log(
        self,
        direction: str,
        topic: str,
        payload: dict,
        operation_type: str = "",
        trigger_reason: str = "",
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        """Append a structured MQTT event to the in-memory log."""
        self._event_log.appendleft(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "dir": direction,
                "topic": topic,
                "payload": payload,
                "operation_type": operation_type,
                "trigger_reason": trigger_reason,
                "qos": qos,
                "retain": retain,
            }
        )

    # -- routes ------------------------------------------------------------ #

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/", response_class=HTMLResponse)
        async def homepage(request: Request):
            return templates.TemplateResponse(
                "homepage.html",
                {
                    "request": request,
                    "cfg": self._cfg,
                    "connected": self._mqtt.connected,
                },
            )

        @app.get("/configuration", response_class=HTMLResponse)
        async def configuration(request: Request):
            return templates.TemplateResponse(
                "configuration.html",
                {"request": request, "cfg": self._cfg},
            )

        @app.get("/stream")
        async def mjpeg_stream():
            return StreamingResponse(
                self._frame_generator(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

        @app.get("/api/status")
        def api_status():
            info = self._video.get_video_info()
            return {
                "mqtt_connected": self._mqtt.connected,
                "edge_id": self._cfg.edge_id,
                "camera_id": self._cfg.camera_id,
                "source_type": info.get("source_type"),
                "current_video": info.get("current_video"),
                "is_paused": info.get("is_paused"),
                "inference_running": self._engine.running,
            }

        @app.get("/api/log")
        def api_log():
            return list(self._event_log)

    # -- MJPEG generator --------------------------------------------------- #

    async def _frame_generator(self):
        while True:
            frame_bytes = await asyncio.get_event_loop().run_in_executor(
                None, self._engine.get_latest_frame
            )
            if frame_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            await asyncio.sleep(self._stream_interval)
