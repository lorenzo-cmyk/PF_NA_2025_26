"""Event Pipeline: bridges InferenceEngine detections to MQTT and handles upload commands."""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import requests

from camera.config import Config

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventPipeline:
    """Assembles detection events, throttles them, and dispatches uploads."""

    def __init__(self, mqtt_client, cfg: Config) -> None:
        # Avoid circular import — type hint as string
        self._mqtt = mqtt_client
        self._cfg = cfg
        self._last_event_time: float = 0.0
        self._image_dir = Path(cfg.image_dir)
        self._image_dir.mkdir(parents=True, exist_ok=True)
        self._upload_executor = ThreadPoolExecutor(max_workers=8)
        log.info("EventPipeline: saving frames to %s", self._image_dir)

    def handle_detections(self, detections: list[dict], frame: np.ndarray) -> None:
        """Callback registered with InferenceEngine.

        Applies throttling, builds the MQTT payload, saves the frame as JPEG,
        and publishes to ``{prefix}/event``.
        """
        now = time.monotonic()
        if now - self._last_event_time < self._cfg.event_throttle_s:
            remaining = self._cfg.event_throttle_s - (now - self._last_event_time)
            log.debug(
                "Detection throttled (%.1fs remaining in throttle window, count=%d)",
                remaining,
                len(detections),
            )
            return
        self._last_event_time = now

        event_id = str(uuid.uuid4())
        capture_time = _ts()

        # Strip the 'box' key — not part of the MQTT payload
        mqtt_detections = [
            {k: v for k, v in d.items() if k != "box"} for d in detections
        ]

        payload = {
            "event_id": event_id,
            "capture_time": capture_time,
            "count": len(detections),
            "detections": mqtt_detections,
        }

        # Save annotated frame
        img_path = self._image_dir / f"{event_id}.jpg"
        try:
            cv2.imwrite(str(img_path), frame)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to save frame for event %s", event_id)

        self._mqtt.publish_event(payload, trigger=f"Auto: detection event {event_id}")
        log.info("Event published: event_id=%s, animals=%d", event_id, len(detections))

    def handle_upload_cmd(self, _topic: str, cmd_payload: dict) -> None:
        """Called when a ``cmd/upload`` message arrives.

        Runs the actual upload in a background thread to avoid blocking
        the MQTT callback.
        """
        event_id = cmd_payload.get("event_id", "")
        upload_url = cmd_payload.get("upload_url", "")
        if not event_id or not upload_url:
            log.warning("cmd/upload missing event_id or upload_url: %s", cmd_payload)
            return
        self._upload_executor.submit(self._do_upload, event_id, upload_url)

    def _do_upload(self, event_id: str, upload_url: str) -> None:
        img_path = self._image_dir / f"{event_id}.jpg"
        if not img_path.is_file():
            log.warning("Image file not found for event_id=%s", event_id)
            self._mqtt.publish_upload_status(
                event_id,
                "ERROR",
                f"Image not found: {event_id}.jpg",
            )
            return

        log.info("Uploading %s → %s", img_path, upload_url)
        try:
            with img_path.open("rb") as f:
                resp = requests.put(
                    upload_url,
                    data=f,
                    headers={"Content-Type": "image/jpeg"},
                    timeout=30,
                )
            resp.raise_for_status()
            log.info("Upload SUCCESS for %s (HTTP %d)", event_id, resp.status_code)
            self._mqtt.publish_upload_status(
                event_id, "SUCCESS", upload_url.split("?")[0]
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.exception("Upload FAILED for %s → %s", event_id, upload_url)
            self._mqtt.publish_upload_status(event_id, "ERROR", str(exc))
