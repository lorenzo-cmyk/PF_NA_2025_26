"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """Application configuration populated from environment variables."""

    # MQTT Broker
    mqtt_host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    mqtt_username: str | None = field(
        default_factory=lambda: os.getenv("MQTT_USERNAME")
    )
    mqtt_password: str | None = field(
        default_factory=lambda: os.getenv("MQTT_PASSWORD")
    )
    mqtt_client_id: str = field(
        default_factory=lambda: os.getenv("MQTT_CLIENT_ID", "camera-emulator")
    )

    # Camera identity
    edge_id: str = field(default_factory=lambda: os.getenv("EDGE_ID", "edge_01"))
    camera_id: str = field(default_factory=lambda: os.getenv("CAMERA_ID", "cam_01"))

    # HTTP dashboard
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "0.0.0.0"))
    web_port: int = field(default_factory=lambda: int(os.getenv("WEB_PORT", "8080")))

    # Scenes file
    scenes_file: str = field(
        default_factory=lambda: os.getenv("SCENES_FILE", "demo_scenes/scenes.json")
    )

    # --- derived helpers -------------------------------------------------- #

    def topic_prefix(self) -> str:
        """Return the MQTT topic prefix for this edge/camera pair."""
        return f"edge/{self.edge_id}/{self.camera_id}"
