"""Message handlers – business logic for Edge and Cloud processing."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import requests as http_requests
from sqlalchemy import text as sa_text

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

# Regex to extract coordinates from "POINT(lon, lat)" or "POINT(lon lat)"
_POINT_RE = re.compile(r"^POINT\(\s*([-\d.]+)[,\s]+([-\d.]+)\s*\)$", re.IGNORECASE)


def _parse_point(value: str | None) -> tuple[float, float] | None:
    """Extract (longitude, latitude) from 'POINT(lon, lat)' or 'POINT(lon lat)'."""
    if value is None:
        return None
    m = _POINT_RE.match(value.strip())
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


class MessageHandler:
    """Routes incoming MQTT messages to the appropriate handler."""

    def __init__(
        self, cfg: Config, mqtt: MQTTClient, engine: Any, s3: S3Client | None
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

        # upload_status is about edge-local S3; the cloud has its own
        # upload flow triggered by cmd/upload, so don't relay it.
        if rest == "event/upload_status":
            log.debug("Not relaying edge upload_status to cloud")
            return

        # Relay processed edge messages to cloud namespace
        cloud_topic = f"cloud/{edge_id}/{camera_id}/{rest}"
        retain = rest in ("lifecycle/birth", "telemetry")
        self._mqtt.publish(cloud_topic, payload, qos=1, retain=retain)
        log.info("Relayed edge → cloud: %s", cloud_topic)

    def _edge_route_cloud_cmd(
        self, edge_id: str, camera_id: str, payload: dict[str, Any]
    ) -> None:
        """Fetch image from local S3 and upload it to the cloud presigned URL."""
        event_id = payload.get("event_id")
        upload_url = payload.get("upload_url")
        if not event_id or not upload_url:
            log.warning("Cloud cmd/upload missing event_id or upload_url – skipping")
            return

        object_key = f"{event_id}.jpg"
        status_topic = f"cloud/{edge_id}/{camera_id}/event/upload_status"

        # Download image from local edge S3
        if not self._s3:
            log.error("S3 client not available – cannot fulfil upload command")
            self._mqtt.publish(
                status_topic,
                {
                    "event_id": event_id,
                    "status": "ERROR",
                    "message": "S3 client unavailable",
                },
                qos=1,
            )
            return

        image_bytes = self._s3.get_object(object_key)
        if image_bytes is None:
            log.warning("Image %s not found in local S3 – cannot upload", object_key)
            self._mqtt.publish(
                status_topic,
                {
                    "event_id": event_id,
                    "status": "ERROR",
                    "message": f"Image {object_key} not found in local storage",
                },
                qos=1,
            )
            return

        # HTTP PUT the image to the cloud presigned URL
        try:
            resp = http_requests.put(
                upload_url,
                data=image_bytes,
                headers={"Content-Type": "image/jpeg"},
                timeout=30,
            )
            resp.raise_for_status()
        except http_requests.RequestException as exc:
            log.error("Failed to upload %s to cloud: %s", object_key, exc)
            self._mqtt.publish(
                status_topic,
                {"event_id": event_id, "status": "ERROR", "message": str(exc)},
                qos=1,
            )
            return

        # Report success
        log.info("Uploaded %s to cloud storage", object_key)
        self._mqtt.publish(
            status_topic,
            {
                "event_id": event_id,
                "status": "SUCCESS",
                "remote_path": upload_url.split("?")[0],
            },
            qos=1,
        )

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
        elif rest == "cmd/upload":
            # cmd/upload on cloud/ are outgoing commands to the edge;
            # the cloud service itself publishes these – ignore.
            log.debug("Ignoring own cmd/upload on cloud topic")
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
            edge_uuid = uuid.UUID(edge_id)
            camera_uuid = uuid.UUID(camera_id)
            with get_session(self._engine) as session:
                # Upsert edge_device (parent – must exist before camera)
                device = session.get(EdgeDevice, edge_uuid)
                if device is None:
                    device = EdgeDevice(
                        edge_id=edge_uuid,
                        name=payload.get("edge_name", edge_id),
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
                camera = session.get(Camera, camera_uuid)
                if camera is None:
                    camera = Camera(
                        camera_id=camera_uuid,
                        edge_id=edge_uuid,
                        type=payload.get("camera_type"),
                        technical_params_json=payload.get("technical_params_json"),
                        elevation=payload.get("elevation"),
                        status="Online",
                    )
                    session.add(camera)
                else:
                    if "camera_type" in payload:
                        camera.type = payload["camera_type"]
                    if "technical_params_json" in payload:
                        camera.technical_params_json = payload["technical_params_json"]
                    if "elevation" in payload:
                        camera.elevation = payload["elevation"]
                    camera.status = "Online"
                    session.add(camera)

                session.flush()

                # Update location_coordinates via raw SQL (PostGIS GEOGRAPHY)
                coords = payload.get("camera_coords")
                if coords:
                    lonlat = _parse_point(coords)
                    if lonlat:
                        lon, lat = lonlat
                        session.execute(
                            sa_text(
                                "UPDATE camera SET location_coordinates = "
                                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography "
                                "WHERE camera_id = :cid"
                            ),
                            {"lon": lon, "lat": lat, "cid": str(camera_uuid)},
                        )

                session.commit()
                log.info("Birth processed OK for edge=%s camera=%s", edge_id, camera_id)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to process birth message")

    def _handle_telemetry(self, camera_id: str, payload: dict[str, Any]) -> None:
        """Update camera status/temperature/battery."""
        log.info("Processing telemetry: camera=%s", camera_id)
        try:
            camera_uuid = uuid.UUID(camera_id)
            with get_session(self._engine) as session:
                camera = session.get(Camera, camera_uuid)
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
        """Insert datasetstore row and animaldetected rows; send upload cmd."""
        event_id = payload.get("event_id")
        if not event_id:
            log.warning("Event message missing event_id – skipping")
            return

        try:
            event_uuid = uuid.UUID(str(event_id))
        except ValueError:
            log.warning("Invalid UUID event_id: %s – skipping", event_id)
            return

        try:
            camera_uuid = uuid.UUID(camera_id)
        except ValueError:
            log.warning("Invalid UUID camera_id: %s – skipping", camera_id)
            return
        log.info("Processing event: %s camera=%s", event_id, camera_id)
        try:
            with get_session(self._engine) as session:
                # Check for duplicate event
                existing = session.get(DatasetStore, event_uuid)
                if existing is not None:
                    log.warning("Duplicate event %s – skipping", event_id)
                    return

                # Insert datasetstore first (parent)
                capture_time_raw = payload.get("capture_time")
                capture_time: datetime | None = None
                if capture_time_raw:
                    try:
                        capture_time = datetime.fromisoformat(
                            capture_time_raw.replace("Z", "+00:00")
                        )
                    except ValueError:
                        log.warning(
                            "Invalid capture_time format %r for event %s – using None",
                            capture_time_raw,
                            event_id,
                        )
                ds = DatasetStore(
                    event_id=event_uuid,
                    camera_id=camera_uuid,
                    time=capture_time,
                    count=payload.get("count", 0),
                    imagepath="",
                )
                session.add(ds)
                # Flush to ensure datasetstore row exists before FK-dependent inserts
                session.flush()

                # Insert detections (children)
                detections = payload.get("detections", [])
                for det in detections:
                    ad = AnimalDetected(
                        event_id=event_uuid,
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
        """Update datasetstore.imagepath on successful upload."""
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

        log.info("Upload success for event %s", event_id)

        try:
            event_uuid = uuid.UUID(str(event_id))
        except ValueError:
            log.warning("Invalid UUID event_id in upload_status: %s", event_id)
            return

        # Derive the clean public URL (no credentials) from the S3 client
        if self._s3:
            public_url = self._s3.get_object_url(f"{event_id}.jpg")
        else:
            public_url = payload.get("remote_path")
            if not public_url:
                log.warning(
                    "No S3 client and no remote_path for %s – cannot update imagepath",
                    event_id,
                )
                return
        try:
            with get_session(self._engine) as session:
                ds = session.get(DatasetStore, event_uuid)
                if ds is None:
                    log.warning(
                        "Upload status for unknown event %s – skipping",
                        event_id,
                    )
                    return
                ds.imagepath = public_url
                session.add(ds)
                session.commit()
                log.info("Image path updated for event %s", event_id)
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Failed to update imagepath for %s", event_id)
