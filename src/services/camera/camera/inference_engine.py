"""Threaded inference loop: reads frames, runs Detector, manages the frame buffer."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import cv2
import numpy as np

from camera.detector import Detector
from camera.video_source import VideoSource

log = logging.getLogger(__name__)


class InferenceEngine:
    """Runs the YOLOv9t detection loop in a dedicated daemon thread."""

    def __init__(
        self,
        detector: Detector,
        video_source: VideoSource,
        target_fps: int = 15,
    ) -> None:
        self._detector = detector
        self._video_source = video_source
        self._target_fps = target_fps

        self._running = False
        self._thread: threading.Thread | None = None

        self._latest_frame: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_detections: list[dict] = []
        self._frame_lock = threading.Lock()

        self._on_detection: Callable[[list[dict], np.ndarray], None] | None = None

    # -- public API -------------------------------------------------------- #

    def start(self) -> None:
        """Start the inference loop in a daemon thread."""
        if self._running:
            return
        self._running = True
        source_fps = self._video_source.get_source_fps()
        if source_fps and source_fps > 0:
            effective = min(self._target_fps, source_fps)
            log.info(
                "InferenceEngine started: source_fps=%.2f, inference_fps=%d → effective_fps=%.2f",
                source_fps,
                self._target_fps,
                effective,
            )
        else:
            log.info(
                "InferenceEngine started: source=live-camera, inference_fps=%d",
                self._target_fps,
            )
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="inference"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to stop and wait for the thread to finish."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("InferenceEngine stopped.")

    def get_latest_frame(self) -> bytes | None:
        """Return the latest annotated frame as JPEG bytes (thread-safe).

        The JPEG encoding is done once in the inference loop; this method
        simply returns the cached bytes.
        """
        with self._frame_lock:
            return self._latest_jpeg

    def get_latest_detections(self) -> list[dict]:
        """Return the latest detection list (thread-safe)."""
        with self._frame_lock:
            return list(self._latest_detections)

    def on_detection(self, callback: Callable[[list[dict], np.ndarray], None]) -> None:
        """Register a callback invoked when detections are found (count > 0)."""
        self._on_detection = callback

    @property
    def running(self) -> bool:
        return self._running

    # -- inference loop ---------------------------------------------------- #

    def _loop(self) -> None:
        source_fps = self._video_source.get_source_fps()
        while self._running:
            t0 = time.monotonic()

            ok, frame = self._video_source.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue

            try:
                annotated, detections = self._detector.detect(frame)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Detection error — skipping frame.")
                time.sleep(0.1)
                continue

            ok_enc, buf = cv2.imencode(
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            with self._frame_lock:
                self._latest_frame = annotated
                self._latest_jpeg = bytes(buf) if ok_enc else None
                self._latest_detections = detections

            if detections and self._on_detection is not None:
                try:
                    self._on_detection(detections, annotated)
                except Exception:  # pylint: disable=broad-exception-caught
                    log.exception("Error in on_detection callback.")

            # Cap inference to the source FPS so we never process faster than
            # the source delivers.  source_fps is read once before the loop
            # (it only changes on source switch, which restarts the engine).
            effective_fps = (
                min(self._target_fps, source_fps)
                if source_fps and source_fps > 0
                else self._target_fps
            )
            interval = 1.0 / effective_fps

            elapsed = time.monotonic() - t0
            sleep_for = interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
