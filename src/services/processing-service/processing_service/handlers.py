"""Message handlers – business logic for Edge and Cloud processing."""

from __future__ import annotations

import logging
import re
from typing import Any

from processing_service.config import Config
from processing_service.database import (
    AnimalDetected,
    Camera,
    DatasetStore,
    EdgeDevice,
    get_session,
)
from processing_service.mqtt_client import MQTTClient
from processing_service.s3_client import S3Client

log = logging.getLogger(__name__)

# Regex patterns to extract edge_id and camera_id from topics
# Matches: {prefix}/{edge_id}/{camera_id}/{rest...}
_TOPIC_RE = re.compile(
    r"^(?P<prefix>edge|cloud)/(?P<edge_id>[^/]+)/(?P<camera_id>[^/]+)/(?P<rest>.+)$"
)

# Regex to convert "POINT(lat, lon)" → "(lat, lon)" for PostgreSQL POINT type
_POINT_RE = re.compile(r"^POINT\((.+)\)$", re.IGNORECASE)


def _normalize_point(value: str | None) -> str | None:
    """Convert 'POINT(x, y)' to '(x, y)' for PostgreSQL POINT columns."""
    if value is None:
        return None
    m = _POINT_RE.match(value.strip())
    if m:
        return f"({m.group(1)})"
    return value


class MessageHandler:
    """Routes incoming MQTT messages to the appropriate handler."""

    def __init__(
        self, cfg: Config, mqtt: MQTTClient, engine: Any, s3: S3Client
    ) -> None:
        self._cfg = cfg
        self._mqtt = mqtt
        self._engine = engine
        self._s3 = s3

    # -- entry point (registered as MQTT callback) ------------------------- #

    def handle(self, topic: str, payload: dict[str, Any]) -> None:
        """Dispatch an incoming message based on topic."""
        m = _TOPIC_RE.match(topic)
        if not m:
            log.warning("Ignoring message on unrecognised topic: %s", topic)
            return

        prefix = m.group("prefix")
        edge_id = m.group("edge_id")
        camera_id = m.group("camera_id")
        rest = m.group("rest")

        if self._cfg.is_edge:
            self._handle_edge(prefix, edge_id, camera_id, rest, payload)
        else:
            self._handle_cloud(prefix, edge_id, camera_id, rest, payload)

    # ====================================================================== #
    #  EDGE MODE
    # ====================================================================== #

    def _handle_edge(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        prefix: str,
        edge_id: str,
        camera_id: str,
        rest: str,
        payload: dict[str, Any],
    ) -> None:
        # Route cloud commands down to extreme-edge
        if prefix == "cloud" and rest == "cmd/upload":
            self._edge_route_cloud_cmd(edge_id, camera_id, payload)
            return

        if prefix != "edge":
            return

        # Process edge messages
        if rest == "lifecycle/birth":
            self._handle_birth(edge_id, camera_id, payload)
        elif rest == "telemetry":
            self._handle_telemetry(camera_id, payload)
        elif rest == "event":
            self._handle_event(edge_id, camera_id, payload)
        elif rest == "event/upload_status":
            self.handle_upload_status(payload)
        elif rest == "cmd/upload":
            # cmd/upload on edge/ are outgoing commands to extreme-edge;
            # do NOT relay them to cloud (would cause an infinite loop).
            log.debug("Ignoring own cmd/upload on edge topic")
            return
        else:
            log.debug("Unhandled edge topic rest=%s", rest)
            return

        # Relay processed edge messages to cloud namespace
        cloud_topic = f"cloud/{edge_id}/{camera_id}/{rest}"
        self._mqtt.publish(cloud_topic, payload, qos=1)
        log.info("Relayed edge → cloud: %s", cloud_topic)

    def _edge_route_cloud_cmd(
        self, edge_id: str, camera_id: str, payload: dict[str, Any]
    ) -> None:
        """Re-publish a cloud upload command down to the extreme-edge."""
        edge_topic = f"edge/{edge_id}/{camera_id}/cmd/upload"
        self._mqtt.publish(edge_topic, payload, qos=1)
        log.info("Routed cloud cmd → edge: %s", edge_topic)

    # ====================================================================== #
    #  CLOUD MODE
    # ====================================================================== #

    def _handle_cloud(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        prefix: str,
        edge_id: str,
        camera_id: str,
        rest: str,
        payload: dict[str, Any],
    ) -> None:
        if prefix != "cloud":
            return

        if rest == "lifecycle/birth":
            self._handle_birth(edge_id, camera_id, payload)
        elif rest == "telemetry":
            self._handle_telemetry(camera_id, payload)
        elif rest == "event":
            self._handle_event(edge_id, camera_id, payload)
        elif rest == "event/upload_status":
            self.handle_upload_status(payload)
        else:
            log.debug("Unhandled cloud topic rest=%s", rest)

    # ====================================================================== #
    #  SHARED DB OPERATIONS
    # ====================================================================== #

    def _handle_birth(
        self, edge_id: str, camera_id: str, payload: dict[str, Any]
    ) -> None:
        """Insert/update edge_device and camera tables."""
        log.info("Processing birth: edge=%s camera=%s", edge_id, camera_id)
        try:
            with get_session(self._engine) as session:
                # Upsert edge_device (parent – must exist before camera)
                device = session.get(EdgeDevice, edge_id)
                if device is None:
                    device = EdgeDevice(
                        edge_id=edge_id,
                        name=payload.get("edge_name"),
                        location=payload.get("edge_location"),
                    )
                    session.add(device)
                else:
                    if "edge_name" in payload:
                        device.name = payload["edge_name"]
                    if "edge_location" in payload:
                        device.location = payload["edge_location"]
                    session.add(device)

                # Flush so edge_device exists for the FK
                session.flush()

                # Upsert camera (child)
                camera = session.get(Camera, camera_id)
                if camera is None:
                    camera = Camera(
                        camera_id=camera_id,
                        edge_id=edge_id,
                        type=payload.get("camera_type"),
                        location_coordinates=_normalize_point(
                            payload.get("camera_coords")
                        ),
                        technical_params_json=payload.get("technical_params_json"),
                        elevation=payload.get("elevation"),
                        status="active",
                    )
                    session.add(camera)
                else:
                    if "camera_type" in payload:
                        camera.type = payload["camera_type"]
                    if "camera_coords" in payload:
                        camera.location_coordinates = _normalize_point(
                            payload["camera_coords"]
                        )
                    if "technical_params_json" in payload:
                        camera.technical_params_json = payload["technical_params_json"]
                    if "elevation" in payload:
                        camera.elevation = payload["elevation"]
                    camera.status = "active"
                    session.add(camera)

                session.commit()
                log.info("Birth processed OK for edge=%s camera=%s", edge_id, camera_id)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to process birth message")

    def _handle_telemetry(self, camera_id: str, payload: dict[str, Any]) -> None:
        """Update camera status/temperature/battery."""
        log.info("Processing telemetry: camera=%s", camera_id)
        try:
            with get_session(self._engine) as session:
                camera = session.get(Camera, camera_id)
                if camera is None:
                    log.warning(
                        "Telemetry for unknown camera %s – skipping",
                        camera_id,
                    )
                    return
                if "status" in payload:
                    camera.status = payload["status"]
                if "temperature" in payload:
                    camera.temperature = payload["temperature"]
                if "battery_level" in payload:
                    camera.battery_level = payload["battery_level"]
                session.add(camera)
                session.commit()
                log.info("Telemetry updated for camera=%s", camera_id)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to process telemetry message")

    def _handle_event(
        self, edge_id: str, camera_id: str, payload: dict[str, Any]
    ) -> None:
        """Insert dataset_store row and animal_detected rows; send upload cmd."""
        event_id = payload.get("event_id")
        if not event_id:
            log.warning("Event message missing event_id – skipping")
            return

        log.info("Processing event: %s camera=%s", event_id, camera_id)
        try:
            with get_session(self._engine) as session:
                # Check for duplicate event
                existing = session.get(DatasetStore, event_id)
                if existing is not None:
                    log.warning("Duplicate event %s – skipping", event_id)
                    return

                # Insert dataset_store first (parent)
                ds = DatasetStore(
                    event_id=event_id,
                    camera_id=camera_id,
                    time=payload.get("capture_time"),
                    count=payload.get("count"),
                    event_coordinates=_normalize_point(
                        payload.get("event_coordinates")
                    ),
                )
                session.add(ds)
                # Flush to ensure dataset_store row exists before FK-dependent inserts
                session.flush()

                # Insert detections (children)
                detections = payload.get("detections", [])
                for det in detections:
                    ad = AnimalDetected(
                        event_id=event_id,
                        animal_type=det.get("animal_type"),
                        distance=det.get("distance"),
                        size_estimate=det.get("size_estimate"),
                        confidence=det.get("confidence"),
                    )
                    session.add(ad)

                session.commit()
                log.info(
                    "Event %s stored with %d detections", event_id, len(detections)
                )
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to process event message")
            return

        # Edge mode: publish upload command to the extreme-edge
        if self._cfg.is_edge and self._s3:
            object_key = f"{event_id}.jpg"
            upload_url = self._s3.generate_presigned_upload_url(object_key)
            cmd_payload = {
                "event_id": event_id,
                "upload_url": upload_url,
            }
            cmd_topic = f"edge/{edge_id}/{camera_id}/cmd/upload"
            self._mqtt.publish(cmd_topic, cmd_payload, qos=1)
            log.info("Upload command sent: %s", cmd_topic)

    def handle_upload_status(self, payload: dict[str, Any]) -> None:
        """Update dataset_store.image_path on successful upload."""
        event_id = payload.get("event_id")
        status = payload.get("status", "").upper()
        if not event_id:
            log.warning("Upload status missing event_id – skipping")
            return

        if status != "SUCCESS":
            log.warning(
                "Upload failed for %s: %s",
                event_id,
                payload.get("message", "unknown error"),
            )
            return

        remote_path = payload.get("remote_path")
        if not remote_path:
            log.warning("Upload status SUCCESS but no remote_path for %s", event_id)
            return

        log.info("Upload success for %s → %s", event_id, remote_path)
        # Derive the clean public URL (no credentials) from the event_id
        if self._s3:
            public_url = self._s3.get_object_url(f"{event_id}.jpg")
        else:
            public_url = remote_path
        try:
            with get_session(self._engine) as session:
                ds = session.get(DatasetStore, event_id)
                if ds is None:
                    log.warning(
                        "Upload status for unknown event %s – skipping",
                        event_id,
                    )
                    return
                ds.image_path = public_url
                session.add(ds)
                session.commit()
                log.info("Image path updated for event %s", event_id)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to update image_path for %s", event_id)
