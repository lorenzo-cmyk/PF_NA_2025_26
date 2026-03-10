"""Video source abstraction: USB camera or pre-recorded video file."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

log = logging.getLogger(__name__)


class VideoSource:
    """Uniform frame-reading interface over a USB camera or a video file."""

    def __init__(
        self,
        usb_index: int,
        samples_dir: str,
        default_source: Literal["usb", "video"] = "usb",
    ) -> None:
        self._usb_index = usb_index
        self._samples_dir = Path(samples_dir)
        self._lock = threading.Lock()
        self._capture: cv2.VideoCapture | None = None
        self._source_type: Literal["usb", "video"] = "usb"
        self._paused = False
        self._last_frame: np.ndarray | None = None

        # Discover available sample videos
        videos_dir = self._samples_dir / "videos"
        self._available_videos: list[dict] = []
        if videos_dir.is_dir():
            for p in sorted(videos_dir.iterdir()):
                if p.suffix.lower() in (".mp4", ".avi"):
                    self._available_videos.append({"name": p.name, "path": str(p)})
        log.info(
            "Discovered %d sample video(s) in %s",
            len(self._available_videos),
            videos_dir,
        )

        self._current_video: str = (
            self._available_videos[0]["name"] if self._available_videos else ""
        )

        # Open the default source
        if default_source == "video" and self._available_videos:
            self._open_video(self._current_video)
        else:
            self._open_usb()

    # -- public API -------------------------------------------------------- #

    def switch(
        self,
        source_type: Literal["usb", "video"],
        video_name: str | None = None,
    ) -> None:
        """Switch the active video source.  Thread-safe."""
        with self._lock:
            if source_type == "usb":
                self._release_capture()
                self._paused = False
                self._last_frame = None
                self._open_usb_locked()
            else:
                target = video_name or self._current_video
                if not target and self._available_videos:
                    target = self._available_videos[0]["name"]
                if self._source_type == "video" and target == self._current_video:
                    # Same video already selected — no-op
                    return
                self._release_capture()
                self._paused = False
                self._last_frame = None
                self._open_video_locked(target)

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Return the next frame.  Thread-safe.

        When the video source reaches EOF, returns a solid black frame
        (``ok=True``) so the stream goes black rather than failing.
        When paused, returns the last frame without advancing the position.
        """
        with self._lock:
            if self._capture is None:
                return False, None

            if self._paused and self._last_frame is not None:
                return True, self._last_frame.copy()

            ok, frame = self._capture.read()

            if not ok:
                if self._source_type == "video":
                    # EOF — return a black frame
                    h = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                    w = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                    black = np.zeros((h, w, 3), dtype=np.uint8)
                    self._last_frame = black
                    return True, black
                return False, None

            self._last_frame = frame
            return True, frame

    def pause(self) -> None:
        """Pause video playback (no-op for USB)."""
        with self._lock:
            if self._source_type == "video":
                self._paused = True

    def resume(self) -> None:
        """Resume video playback (no-op for USB)."""
        with self._lock:
            if self._source_type == "video":
                self._paused = False

    def seek(self, timestamp_ms: float) -> None:
        """Seek to a timestamp in the video.  Only works when paused."""
        with self._lock:
            if self._source_type != "video" or not self._paused:
                return
            if self._capture is not None:
                self._capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
                ok, frame = self._capture.read()
                if ok and frame is not None:
                    self._last_frame = frame

    def get_video_info(self) -> dict:
        """Return metadata about the current video source."""
        with self._lock:
            if self._source_type == "video" and self._capture is not None:
                pos_ms: float | None = self._capture.get(cv2.CAP_PROP_POS_MSEC)
                fps = self._capture.get(cv2.CAP_PROP_FPS) or 0
                total_frames = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
                duration_ms: float | None = (
                    (total_frames / fps * 1000) if fps > 0 else None
                )
            else:
                pos_ms = None
                duration_ms = None

            return {
                "source_type": self._source_type,
                "current_video": self._current_video,
                "is_paused": self._paused,
                "position_ms": pos_ms,
                "duration_ms": duration_ms,
                "fps": (
                    self._capture.get(cv2.CAP_PROP_FPS)
                    if self._capture is not None
                    else None
                ),
            }

    def get_source_fps(self) -> float | None:
        """Return the native FPS of the current source.

        For a video file, this is the value encoded in the container (e.g. 2 FPS
        for a 2-FPS timelapse).  For a USB camera, returns ``None`` — the camera
        hardware controls its own capture rate and we rely on ``inference_fps``
        as the processing cap.
        """
        with self._lock:
            if self._source_type != "video" or self._capture is None:
                return None
            fps = self._capture.get(cv2.CAP_PROP_FPS)
            return fps if fps > 0 else None

    def list_videos(self) -> list[dict]:
        """Return the list of available sample videos."""
        return list(self._available_videos)

    def release(self) -> None:
        """Release the OpenCV capture."""
        with self._lock:
            self._release_capture()

    # -- lock-held helpers ------------------------------------------------- #

    def _open_usb(self) -> None:
        with self._lock:
            self._open_usb_locked()

    def _open_usb_locked(self) -> None:
        cap = cv2.VideoCapture(self._usb_index)
        if not cap.isOpened():
            log.warning("Could not open USB camera at index %d", self._usb_index)
        self._capture = cap
        self._source_type = "usb"
        log.info("VideoSource → USB camera (index=%d)", self._usb_index)

    def _open_video(self, video_name: str) -> None:
        with self._lock:
            self._open_video_locked(video_name)

    def _open_video_locked(self, video_name: str) -> None:
        path = self._resolve_video_path(video_name)
        if path is None:
            log.warning("Sample video %r not found; falling back to USB.", video_name)
            self._open_usb_locked()
            return
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            log.warning("Could not open video file %s; falling back to USB.", path)
            self._open_usb_locked()
            return
        self._capture = cap
        self._source_type = "video"
        self._current_video = video_name
        log.info("VideoSource → video file: %s", path)

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _resolve_video_path(self, video_name: str) -> Path | None:
        for v in self._available_videos:
            if v["name"] == video_name:
                return Path(v["path"])
        return None
