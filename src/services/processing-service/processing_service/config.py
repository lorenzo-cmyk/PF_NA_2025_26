"""Configuration loaded from a .env file (if present) or environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file:
# processing_service/config.py → processing_service/ → <service root>).
# If the file does not exist this is a no-op; existing env vars are preserved.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)


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
            "postgresql://watchedge:watchedge@localhost:5432/watchedge-db",
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

    def log(self) -> None:
        """Log the full resolved configuration at INFO level."""
        import logging  # pylint: disable=import-outside-toplevel
        _log = logging.getLogger(__name__)
        _log.info("=== Processing Service Configuration ===")
        _log.info("  [Mode]")
        _log.info("    SERVICE_MODE          = %s", self.service_mode.value)
        _log.info("  [MQTT]")
        _log.info("    MQTT_BROKER_URL       = %s", self.mqtt_broker_url)
        _log.info("    MQTT_CLIENT_ID        = %s", self.mqtt_client_id)
        _log.info("  [Database]")
        _log.info("    DATABASE_URL          = %s", self.database_url)
        _log.info("  [Object Storage]")
        _log.info("    OBJECT_STORAGE_URL    = %s", self.object_storage_url)
        _log.info("    S3_PUBLIC_URL         = %s", self.s3_public_url or "(same as OBJECT_STORAGE_URL)")
        _log.info("    S3_ACCESS_KEY         = %s", self.s3_access_key)
        _log.info("    S3_SECRET_KEY         = %s", "***")
        _log.info("    S3_BUCKET             = %s", self.s3_bucket)
        _log.info("  [HTTP Server]")
        _log.info("    WEB_HOST              = %s", self.web_host)
        _log.info("    WEB_PORT              = %d", self.web_port)
        _log.info("=======================================")
