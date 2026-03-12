"""Configuration loaded from a .env file (if present) or environment variables."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env path relative to this file so it is found regardless of the
# working directory when the service starts.
_ENV_FILE = str(Path(__file__).parent.parent / ".env")


class ServiceMode(str, Enum):
    """Operational mode of the processing service."""

    EDGE = "EDGE"
    CLOUD = "CLOUD"


class Config(BaseSettings):  # pylint: disable=too-many-instance-attributes
    """Application configuration parsed and validated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # Service mode
    service_mode: ServiceMode = ServiceMode.EDGE

    # MQTT Broker
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = ""

    # Database
    database_url: str = "postgresql://watchedge:watchedge@localhost:5432/watchedge-db"

    # Object Storage (S3-compatible)
    object_storage_url: str = "http://localhost:9000"
    s3_access_key: str = "watchedge"
    s3_secret_key: str = "watchedge"
    s3_bucket: str = "watchedge-images"
    s3_public_url: str = ""

    # HTTP server
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8000, ge=1, le=65535)

    # --- derived helpers -------------------------------------------------- #

    @property
    def is_edge(self) -> bool:
        """Return True when running in EDGE mode."""
        return self.service_mode == ServiceMode.EDGE

    @property
    def is_cloud(self) -> bool:
        """Return True when running in CLOUD mode."""
        return self.service_mode == ServiceMode.CLOUD

    def log(self) -> None:
        """Log the full resolved configuration at INFO level."""
        _log = logging.getLogger(__name__)
        _log.info("=== Processing Service Configuration ===")
        _log.info("  [Mode]")
        _log.info("    SERVICE_MODE          = %s", self.service_mode.value)
        _log.info("  [MQTT]")
        _log.info("    MQTT_HOST             = %s", self.mqtt_host)
        _log.info("    MQTT_PORT             = %d", self.mqtt_port)
        _log.info("    MQTT_USERNAME         = %s", self.mqtt_username or "(none)")
        _log.info(
            "    MQTT_PASSWORD         = %s", "***" if self.mqtt_password else "(none)"
        )
        _log.info("    MQTT_CLIENT_ID        = %s", self.mqtt_client_id or "(auto)")
        _log.info("  [Database]")
        _log.info("    DATABASE_URL          = %s", self.database_url)
        _log.info("  [Object Storage]")
        _log.info("    OBJECT_STORAGE_URL    = %s", self.object_storage_url)
        _log.info(
            "    S3_PUBLIC_URL         = %s",
            self.s3_public_url or "(same as OBJECT_STORAGE_URL)",
        )
        _log.info("    S3_ACCESS_KEY         = %s", self.s3_access_key)
        _log.info("    S3_SECRET_KEY         = %s", "***")
        _log.info("    S3_BUCKET             = %s", self.s3_bucket)
        _log.info("  [HTTP Server]")
        _log.info("    WEB_HOST              = %s", self.web_host)
        _log.info("    WEB_PORT              = %d", self.web_port)
        _log.info("=======================================")
