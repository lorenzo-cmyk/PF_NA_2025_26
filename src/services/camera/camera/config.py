"""Configuration loaded from a .env file (if present) or environment variables."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env path relative to this file so it is found regardless of the
# working directory when the service starts.
_ENV_FILE = str(Path(__file__).parent.parent / ".env")


class Config(BaseSettings):  # pylint: disable=too-many-instance-attributes
    """Application configuration parsed and validated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # MQTT Broker
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = ""

    # Camera identity — required UUIDs provisioned at deployment time
    edge_id: str
    camera_id: str

    # HTTP WebUI
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8080, ge=1, le=65535)

    # Inference
    model_path: str = "model/best_yolov9t_aug.onnx"
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    iou_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    usb_camera_index: int = Field(default=0, ge=0)

    # Sample assets
    samples_dir: str = "samples/"
    scenes_file: str = "samples/scenes.json"

    # Runtime
    default_source: Literal["usb", "video"] = "video"
    inference_fps: int = Field(default=5, ge=1, le=120)
    event_throttle_s: float = Field(default=1.0, gt=0.0)
    image_dir: str = "data/images/"
    telemetry_interval_s: float = Field(default=30.0, gt=0.0)

    # Birth / registration defaults
    birth_edge_name: str = "SAN_ROSSORE_PARK"
    birth_edge_location: str = "San Rossore Park (PI, Italy)"
    birth_camera_type: str = "EXTREME_EDGE_CAMERA_V8"
    birth_camera_coords: str = "POINT(43.7233401, 10.3365951)"
    birth_elevation: int = 20
    birth_technical_params_json: str = '{"res": "2568x1724"}'

    # --- validators ------------------------------------------------------ #

    @field_validator("edge_id", "camera_id")
    @classmethod
    def _validate_uuid(cls, v: str, info: ValidationInfo) -> str:
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(
                f"{info.field_name.upper()}={v!r} is not a valid UUID. "
                "Provision a proper UUID (e.g. via uuidgen)."
            ) from exc
        return v

    @field_validator("birth_technical_params_json")
    @classmethod
    def _validate_json(cls, v: str) -> str:
        try:
            json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"BIRTH_TECHNICAL_PARAMS_JSON must be valid JSON: {exc}"
            ) from exc
        return v

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
        _log.info(
            "    MQTT_PASSWORD             = %s",
            "***" if self.mqtt_password else "(none)",
        )
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
        _log.info(
            "    BIRTH_TECHNICAL_PARAMS    = %s", self.birth_technical_params_json
        )
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
