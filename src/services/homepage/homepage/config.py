"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceLink:
    """A single link displayed on the homepage."""

    label: str
    url: str
    description: str
    section: str  # "extreme-edge" | "edge" | "cloud"


@dataclass(frozen=True)
class Config:
    """Application configuration populated from environment variables."""

    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8090")))

    # Extreme-Edge
    camera_emulator_1_url: str = field(
        default_factory=lambda: os.getenv(
            "CAMERA_EMULATOR_1_URL", "http://localhost:8080"
        )
    )
    camera_emulator_2_url: str = field(
        default_factory=lambda: os.getenv(
            "CAMERA_EMULATOR_2_URL", "http://localhost:8081"
        )
    )

    # Edge
    edge_processing_url: str = field(
        default_factory=lambda: os.getenv(
            "EDGE_PROCESSING_URL", "http://localhost:8000"
        )
    )
    edge_grafana_url: str = field(
        default_factory=lambda: os.getenv("EDGE_GRAFANA_URL", "http://localhost:3000")
    )
    edge_rustfs_console_url: str = field(
        default_factory=lambda: os.getenv(
            "EDGE_RUSTFS_CONSOLE_URL", "http://localhost:9001"
        )
    )

    # Cloud
    cloud_processing_url: str = field(
        default_factory=lambda: os.getenv(
            "CLOUD_PROCESSING_URL", "http://localhost:8001"
        )
    )
    cloud_grafana_url: str = field(
        default_factory=lambda: os.getenv("CLOUD_GRAFANA_URL", "http://localhost:3001")
    )
    cloud_rustfs_console_url: str = field(
        default_factory=lambda: os.getenv(
            "CLOUD_RUSTFS_CONSOLE_URL", "http://localhost:9003"
        )
    )

    def links(self) -> list[ServiceLink]:
        """Build the ordered list of service links."""
        return [
            # Extreme-Edge
            ServiceLink(
                label="Camera Emulator 1 (cam_01)",
                url=self.camera_emulator_1_url,
                description="Camera trap emulator dashboard",
                section="extreme-edge",
            ),
            ServiceLink(
                label="Camera Emulator 2 (cam_02)",
                url=self.camera_emulator_2_url,
                description="Camera trap emulator dashboard",
                section="extreme-edge",
            ),
            # Edge
            ServiceLink(
                label="Edge Processing Service",
                url=self.edge_processing_url,
                description="Edge processing API",
                section="edge",
            ),
            ServiceLink(
                label="Edge Grafana",
                url=self.edge_grafana_url,
                description="Edge monitoring dashboards",
                section="edge",
            ),
            ServiceLink(
                label="Edge Object Storage (RustFS)",
                url=self.edge_rustfs_console_url,
                description="Edge S3-compatible storage console",
                section="edge",
            ),
            # Cloud
            ServiceLink(
                label="Cloud Processing Service",
                url=self.cloud_processing_url,
                description="Cloud processing API",
                section="cloud",
            ),
            ServiceLink(
                label="Cloud Grafana",
                url=self.cloud_grafana_url,
                description="Cloud monitoring dashboards",
                section="cloud",
            ),
            ServiceLink(
                label="Cloud Object Storage (RustFS)",
                url=self.cloud_rustfs_console_url,
                description="Cloud S3-compatible storage console",
                section="cloud",
            ),
        ]
