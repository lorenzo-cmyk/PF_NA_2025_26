"""WatchEdge Camera Service — application entry point (inside package)."""

from __future__ import annotations

import json
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from camera.config import Config
from camera.video_source import VideoSource
from camera.detector import Detector
from camera.inference_engine import InferenceEngine
from camera.mqtt_client import MQTTClient
from camera.event_pipeline import EventPipeline
from camera.web import WebUI
from camera.api import WebAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)


def _load_scenes(path: str) -> list[dict]:
    p = Path(path)
    if not p.is_absolute():
        # Resolve relative to the service root (parent of camera/)
        p = Path(__file__).resolve().parent.parent / p
    if not p.exists():
        log.warning("Scenes file %s not found – starting with no scenes.", p)
        return []
    with p.open(encoding="utf-8") as f:
        scenes = json.load(f)
    log.info("Loaded %d scene(s) from %s", len(scenes), p)
    return scenes


def main() -> None:
    """Boot the camera service."""
    # 1. Load configuration
    cfg = Config()
    cfg.log()

    # 2. Load sample scenes
    scenes = _load_scenes(cfg.scenes_file)

    # 3. Create VideoSource (discovers sample videos on construction)
    video_source = VideoSource(
        usb_index=cfg.usb_camera_index,
        samples_dir=cfg.samples_dir,
        default_source=cfg.default_source,  # type: ignore[arg-type]
    )

    # 4. Create Detector — resolve model path relative to service root
    model_path = cfg.model_path
    p = Path(model_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    detector = Detector(
        model_path=str(p),
        confidence_threshold=cfg.confidence_threshold,
        iou_threshold=cfg.iou_threshold,
    )

    # 5. Create InferenceEngine
    inference_engine = InferenceEngine(
        detector=detector,
        video_source=video_source,
        target_fps=cfg.inference_fps,
    )

    # 6. Create MQTTClient
    mqtt = MQTTClient(cfg)

    # 7. Create EventPipeline
    event_pipeline = EventPipeline(mqtt_client=mqtt, cfg=cfg)

    # 8. Wire callbacks
    inference_engine.on_detection(event_pipeline.handle_detections)
    mqtt.on_command(event_pipeline.handle_upload_cmd)

    # 9. Create WebUI and WebAPI
    web_ui = WebUI(cfg=cfg, mqtt=mqtt, inference_engine=inference_engine, video_source=video_source)
    web_api = WebAPI(
        inference_engine=inference_engine,
        mqtt=mqtt,
        video_source=video_source,
        event_pipeline=event_pipeline,
        cfg=cfg,
        scenes=scenes,
    )

    # 10. Mount WebAPI router and wire log callback
    web_ui.app.include_router(web_api.router)
    mqtt.on_log_event(web_ui.append_log)

    # 11. Shutdown handler
    def _shutdown(sig, _frame):
        log.info("Shutting down (signal %s)…", signal.Signals(sig).name)
        inference_engine.stop()
        mqtt.stop()
        video_source.release()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 12. Start InferenceEngine
    inference_engine.start()

    # 13. Start MQTT (ignore initial connection errors)
    try:
        mqtt.start(trigger="Auto: application startup")
    except OSError:
        log.exception("Could not connect to MQTT broker – WebUI will start anyway.")

    # 14. Start FastAPI/Uvicorn (blocks on main thread)
    log.info("WebUI → http://%s:%s", cfg.web_host, cfg.web_port)
    uvicorn.run(
        web_ui.app,
        host=cfg.web_host,
        port=cfg.web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
