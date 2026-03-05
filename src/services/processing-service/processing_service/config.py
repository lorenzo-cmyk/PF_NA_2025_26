"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class ServiceMode(str, Enum):
    """Operational mode of the processing service."""

    EDGE = "EDGE"
    CLOUD = "CLOUD"


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """Application configuration populated from environment variables."""

    # Service mode
    service_mode: ServiceMode = field(
        default_factory=lambda: ServiceMode(os.getenv("SERVICE_MODE", "EDGE").upper())
    )

    # MQTT Broker
    mqtt_broker_url: str = field(
        default_factory=lambda: os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883")
    )

    # Database
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql://gBOAR:gBOAR@localhost:5432/gBOAR",
        )
    )

    # Object Storage (S3-compatible)
    object_storage_url: str = field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_URL", "http://localhost:9000")
    )
    s3_access_key: str = field(
        default_factory=lambda: os.getenv("S3_ACCESS_KEY", "gBOAR")
    )
    s3_secret_key: str = field(
        default_factory=lambda: os.getenv("S3_SECRET_KEY", "gBOARpass")
    )
    s3_bucket: str = field(
        default_factory=lambda: os.getenv("S3_BUCKET", "gboar-images")
    )
    s3_public_url: str = field(default_factory=lambda: os.getenv("S3_PUBLIC_URL", ""))

    # HTTP server
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "0.0.0.0"))
    web_port: int = field(default_factory=lambda: int(os.getenv("WEB_PORT", "8000")))

    # MQTT client id
    mqtt_client_id: str = field(
        default_factory=lambda: os.getenv("MQTT_CLIENT_ID", "processing-service")
    )

    # --- derived helpers -------------------------------------------------- #

    @property
    def is_edge(self) -> bool:
        """Return True when running in EDGE mode."""
        return self.service_mode == ServiceMode.EDGE

    @property
    def is_cloud(self) -> bool:
        """Return True when running in CLOUD mode."""
        return self.service_mode == ServiceMode.CLOUD

    @property
    def mqtt_host(self) -> str:
        """Extract host from mqtt_broker_url (mqtt://host:port)."""
        url = self.mqtt_broker_url
        # Strip scheme
        if "://" in url:
            url = url.split("://", 1)[1]
        return url.split(":")[0]

    @property
    def mqtt_port(self) -> int:
        """Extract port from mqtt_broker_url (mqtt://host:port)."""
        url = self.mqtt_broker_url
        if "://" in url:
            url = url.split("://", 1)[1]
        parts = url.split(":")
        if len(parts) > 1:
            return int(parts[1].split("/")[0])
        return 1883
