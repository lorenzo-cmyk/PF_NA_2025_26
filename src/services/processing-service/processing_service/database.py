"""SQLModel database models and engine setup for the WatchEdge database."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, Session, SQLModel, create_engine, JSON, Column


class EdgeDevice(SQLModel, table=True):
    """Top-level entity representing a physical edge computing node."""

    __tablename__ = "edge_device"

    edge_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    location: str | None = None


class Camera(SQLModel, table=True):
    """Imaging hardware – child of edge_device."""

    __tablename__ = "camera"

    camera_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    edge_id: uuid.UUID = Field(foreign_key="edge_device.edge_id")
    type: str | None = None
    # location_coordinates is GEOGRAPHY(Point, 4326) in the DB;
    # handled via raw SQL, not mapped here.
    technical_params_json: dict | None = Field(default=None, sa_column=Column(JSON))
    elevation: float | None = None
    status: str = "Offline"
    temperature: float | None = None
    battery_level: float | None = None


class DatasetStore(SQLModel, table=True):
    """Captured image event – child of camera."""

    __tablename__ = "datasetstore"

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    camera_id: uuid.UUID = Field(foreign_key="camera.camera_id")
    time: datetime | None = None
    count: int = 0
    imagepath: str = ""


class AnimalDetected(SQLModel, table=True):
    """AI inference result – child of datasetstore."""

    __tablename__ = "animaldetected"

    detection_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    event_id: uuid.UUID = Field(foreign_key="datasetstore.event_id")
    animal_type: str | None = None
    distance: float | None = None
    size_estimate: float | None = None
    confidence: float | None = None


def get_engine(database_url: str):
    """Create a SQLAlchemy engine from a database URL."""
    return create_engine(database_url, echo=False)


def get_session(engine) -> Session:
    """Create a new database session."""
    return Session(engine)
