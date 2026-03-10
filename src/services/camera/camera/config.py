"""Configuration loaded from a .env file (if present) or environment variables."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file: camera/config.py
# → camera/ → <service root>). If the file does not exist, this is a no-op and
# the existing environment variables are used unchanged.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)


def _required(var: str) -> str:
    val = os.getenv(var)
    if not val:
        raise RuntimeError(f"Required environment variable {var!r} is not set.")
    return val


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """Application configuration populated from environment variables."""

    # MQTT Broker
    mqtt_host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    mqtt_username: str = field(default_factory=lambda: os.getenv("MQTT_USERNAME", ""))
    mqtt_password: str = field(default_factory=lambda: os.getenv("MQTT_PASSWORD", ""))
    mqtt_client_id: str = field(
        default_factory=lambda: os.getenv("MQTT_CLIENT_ID", "")
    )

    # Camera identity — required UUIDs provisioned at deployment time
    edge_id: str = field(default_factory=lambda: _required("EDGE_ID"))
    camera_id: str = field(default_factory=lambda: _required("CAMERA_ID"))

    # HTTP WebUI
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "0.0.0.0"))
    web_port: int = field(default_factory=lambda: int(os.getenv("WEB_PORT", "8080")))

    # Inference
    model_path: str = field(
        default_factory=lambda: os.getenv("MODEL_PATH", "model/best_yolov9t_aug.onnx")
    )
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))
    )
    iou_threshold: float = field(
        default_factory=lambda: float(os.getenv("IOU_THRESHOLD", "0.5"))
    )
    usb_camera_index: int = field(
        default_factory=lambda: int(os.getenv("USB_CAMERA_INDEX", "0"))
    )

    # Sample assets
    samples_dir: str = field(
        default_factory=lambda: os.getenv("SAMPLES_DIR", "samples/")
    )
    scenes_file: str = field(
        default_factory=lambda: os.getenv("SCENES_FILE", "samples/scenes.json")
    )

    # Runtime
    default_source: str = field(
        default_factory=lambda: os.getenv("DEFAULT_SOURCE", "usb")
    )
    inference_fps: int = field(
        default_factory=lambda: int(os.getenv("INFERENCE_FPS", "15"))
    )
    event_throttle_s: float = field(
        default_factory=lambda: float(os.getenv("EVENT_THROTTLE_S", "5.0"))
    )
    image_dir: str = field(
        default_factory=lambda: os.getenv("IMAGE_DIR", "data/images/")
    )
    telemetry_interval_s: float = field(
        default_factory=lambda: float(os.getenv("TELEMETRY_INTERVAL_S", "30.0"))
    )

    # Birth / registration defaults
    birth_edge_name: str = field(
        default_factory=lambda: os.getenv("BIRTH_EDGE_NAME", "MY_EDGE")
    )
    birth_edge_location: str = field(
        default_factory=lambda: os.getenv("BIRTH_EDGE_LOCATION", "Unknown Location")
    )
    birth_camera_type: str = field(
        default_factory=lambda: os.getenv("BIRTH_CAMERA_TYPE", "BOAR_CAMERA_V3")
    )
    birth_camera_coords: str = field(
        default_factory=lambda: os.getenv("BIRTH_CAMERA_COORDS", "POINT(0.0, 0.0)")
    )
    birth_elevation: int = field(
        default_factory=lambda: int(os.getenv("BIRTH_ELEVATION", "0"))
    )
    birth_technical_params_json: str = field(
        default_factory=lambda: os.getenv(
            "BIRTH_TECHNICAL_PARAMS_JSON", '{"iso": 800, "res": "2160x3840"}'
        )
    )

    # --- validation ------------------------------------------------------ #

    def __post_init__(self) -> None:
        for var, val in (("EDGE_ID", self.edge_id), ("CAMERA_ID", self.camera_id)):
            try:
                uuid.UUID(val)
            except ValueError as exc:
                raise ValueError(
                    f"{var}={val!r} is not a valid UUID. "
                    "Provision a proper UUID (e.g. via uuidgen)."
                ) from exc

    # --- helpers ---------------------------------------------------------- #

    def log(self) -> None:
        """Log the full resolved configuration at INFO level."""
        _log = logging.getLogger(__name__)
        _log.info("=== Camera Service Configuration ===")
        _log.info("  [Identity]")
        _log.info("    EDGE_ID                   = %s", self.edge_id)
        _log.info("    CAMERA_ID                 = %s", self.camera_id)
        _log.info("  [MQTT]")
        _log.info("    MQTT_HOST                 = %s", self.mqtt_host)
        _log.info("    MQTT_PORT                 = %d", self.mqtt_port)
        _log.info("    MQTT_USERNAME             = %s", self.mqtt_username or "(none)")
        _log.info("    MQTT_PASSWORD             = %s", "***" if self.mqtt_password else "(none)")
        _log.info("    MQTT_CLIENT_ID            = %s", self.mqtt_client_id or "(auto)")
        _log.info("  [WebUI]")
        _log.info("    WEB_HOST                  = %s", self.web_host)
        _log.info("    WEB_PORT                  = %d", self.web_port)
        _log.info("  [Inference]")
        _log.info("    MODEL_PATH                = %s", self.model_path)
        _log.info("    CONFIDENCE_THRESHOLD      = %.2f", self.confidence_threshold)
        _log.info("    IOU_THRESHOLD             = %.2f", self.iou_threshold)
        _log.info("    INFERENCE_FPS             = %d", self.inference_fps)
        _log.info("  [Video Source]")
        _log.info("    DEFAULT_SOURCE            = %s", self.default_source)
        _log.info("    USB_CAMERA_INDEX          = %d", self.usb_camera_index)
        _log.info("    SAMPLES_DIR               = %s", self.samples_dir)
        _log.info("    SCENES_FILE               = %s", self.scenes_file)
        _log.info("  [Events]")
        _log.info("    EVENT_THROTTLE_S          = %.1f", self.event_throttle_s)
        _log.info("    IMAGE_DIR                 = %s", self.image_dir)
        _log.info("    TELEMETRY_INTERVAL_S      = %.1f", self.telemetry_interval_s)
        _log.info("  [Birth / Registration]")
        _log.info("    BIRTH_EDGE_NAME           = %s", self.birth_edge_name)
        _log.info("    BIRTH_EDGE_LOCATION       = %s", self.birth_edge_location)
        _log.info("    BIRTH_CAMERA_TYPE         = %s", self.birth_camera_type)
        _log.info("    BIRTH_CAMERA_COORDS       = %s", self.birth_camera_coords)
        _log.info("    BIRTH_ELEVATION           = %d", self.birth_elevation)
        _log.info("    BIRTH_TECHNICAL_PARAMS    = %s", self.birth_technical_params_json)
        _log.info("===================================")

    def topic_prefix(self) -> str:
        """Return the MQTT topic prefix for this edge/camera pair."""
        return f"edge/{self.edge_id}/{self.camera_id}"

    def birth_payload(self) -> dict:
        """Return the birth registration payload derived from config."""
        try:
            technical_params = json.loads(self.birth_technical_params_json)
        except (json.JSONDecodeError, ValueError):
            technical_params = {}
        return {
            "edge_name": self.birth_edge_name,
            "edge_location": self.birth_edge_location,
            "camera_type": self.birth_camera_type,
            "camera_coords": self.birth_camera_coords,
            "elevation": self.birth_elevation,
            "technical_params_json": technical_params,
        }
