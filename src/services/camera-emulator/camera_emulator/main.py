"""Camera Emulator – entry point.

Starts the MQTT client and the FastAPI dashboard.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import uvicorn

from camera_emulator.config import Config
from camera_emulator.mqtt_client import MQTTClient
from camera_emulator import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)


def _load_scenes(path: str) -> tuple[list[dict], Path | None]:
    """Load scenes from *path* and resolve photo references.

    Returns ``(scenes, scenes_dir)`` where *scenes_dir* is the directory
    containing the scenes file (used to locate photo files).
    """
    p = Path(path)
    if not p.is_absolute():
        # Resolve relative to the project root (where pyproject.toml lives)
        p = Path(__file__).resolve().parent.parent / p
    if not p.exists():
        log.warning("Scenes file %s not found – starting with no scenes.", p)
        return [], None
    with p.open(encoding="utf-8") as f:
        scenes = json.load(f)
    scenes_dir = p.resolve().parent
    # Resolve photo paths relative to the scenes file directory
    for scene in scenes:
        photo = scene.get("photo")
        if photo:
            photo_path = scenes_dir / photo
            if not photo_path.exists():
                log.warning(
                    "Photo %s not found for scene '%s'", photo_path, scene.get("name")
                )
    log.info("Loaded %d scene(s) from %s", len(scenes), p)
    return scenes, scenes_dir


def main() -> None:
    """Boot the camera-emulator: MQTT client + HTTP dashboard."""
    cfg = Config()
    scenes, scenes_dir = _load_scenes(cfg.scenes_file)

    mqtt = MQTTClient(cfg)

    # Wire the web module
    web.init(cfg, mqtt, scenes, scenes_dir)

    # Start MQTT
    try:
        mqtt.start(trigger="Auto: application startup")
    except OSError:
        log.exception("Could not connect to MQTT broker – dashboard will start anyway")

    # Start HTTP
    log.info("Dashboard → http://%s:%s", cfg.web_host, cfg.web_port)
    uvicorn.run(
        web.app,
        host=cfg.web_host,
        port=cfg.web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
