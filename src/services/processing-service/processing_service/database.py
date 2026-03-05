"""SQLModel database models and engine setup for gBOAR."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, Session, SQLModel, create_engine, JSON, Column


class EdgeDevice(SQLModel, table=True):
    """Top-level entity representing a physical edge computing node."""

    __tablename__ = "edge_device"

    edge_id: str = Field(primary_key=True)
    name: str | None = None
    location: str | None = None


class Camera(SQLModel, table=True):
    """Imaging hardware – child of edge_device."""

    __tablename__ = "camera"

    camera_id: str = Field(primary_key=True)
    edge_id: str = Field(foreign_key="edge_device.edge_id")
    type: str | None = None
    # POINT stored as text string for SQLModel compatibility
    location_coordinates: str | None = None
    technical_params_json: dict | None = Field(default=None, sa_column=Column(JSON))
    elevation: float | None = None
    status: str | None = None
    temperature: float | None = None
    battery_level: int | None = None


class DatasetStore(SQLModel, table=True):
    """Captured image event – child of camera."""

    __tablename__ = "dataset_store"

    event_id: str = Field(primary_key=True)
    camera_id: str = Field(foreign_key="camera.camera_id")
    time: datetime | None = None
    count: int | None = None
    image_path: str | None = None
    event_coordinates: str | None = None


class AnimalDetected(SQLModel, table=True):
    """AI inference result – child of dataset_store."""

    __tablename__ = "animal_detected"

    detection_id_uuid: str = Field(
        primary_key=True,
        default_factory=lambda: str(uuid.uuid4()),
    )
    event_id: str = Field(foreign_key="dataset_store.event_id")
    animal_type: str | None = None
    distance: float | None = None
    size_estimate: str | None = None
    confidence: float | None = None


def get_engine(database_url: str):
    """Create a SQLAlchemy engine from a database URL."""
    return create_engine(database_url, echo=False)


def get_session(engine) -> Session:
    """Create a new database session."""
    return Session(engine)
