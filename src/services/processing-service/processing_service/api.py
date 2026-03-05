"""FastAPI application – health check + Cloud REST API for image retrieval."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import requests as http_requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from processing_service.config import Config
from processing_service.database import Camera, DatasetStore, get_session
from processing_service.mqtt_client import MQTTClient
from processing_service.s3_client import S3Client

log = logging.getLogger(__name__)

# Shared state – set by init()
_cfg: Config
_mqtt: MQTTClient
_engine: Any = None  # pylint: disable=invalid-name
_s3: S3Client | None = None  # pylint: disable=invalid-name

# Track pending upload completions for the cloud image retrieval flow
# { event_id: threading.Event }
_upload_events: dict[str, threading.Event] = {}
_upload_lock = threading.Lock()

app = FastAPI(title="gBOAR Processing Service")


def init(
    cfg: Config, mqtt_client: MQTTClient, engine: Any, s3: S3Client | None = None
) -> None:
    """Wire up shared state before the app starts."""
    global _cfg, _mqtt, _engine, _s3  # pylint: disable=global-statement
    _cfg = cfg
    _mqtt = mqtt_client
    _engine = engine
    _s3 = s3


# --------------------------------------------------------------------------- #
#  Upload-status notification (used by Cloud image retrieval)
# --------------------------------------------------------------------------- #


def notify_upload_complete(event_id: str) -> None:
    """Signal that an image upload has completed for *event_id*."""
    with _upload_lock:
        evt = _upload_events.get(event_id)
        if evt is not None:
            evt.set()


# --------------------------------------------------------------------------- #
#  Health check
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check."""
    return {
        "status": "ok",
        "mode": _cfg.service_mode.value,
        "mqtt_connected": str(_mqtt.connected),
    }


# --------------------------------------------------------------------------- #
#  Cloud-only: image retrieval endpoint
# --------------------------------------------------------------------------- #


@app.get("/api/v1/images/{event_id}")
async def get_image(event_id: str) -> Response:
    """Retrieve an image for the given event.

    1. Look up the event in the database to get image_path.
    2. Try fetching the image from Cloud Object Storage.
    3. If not available, publish an upload command and wait for the image.
    4. Return the image bytes to the caller.
    """
    if not _cfg.is_cloud:
        raise HTTPException(
            status_code=404,
            detail="Image retrieval is only available in CLOUD mode",
        )

    # Look up the event in the DB
    with get_session(_engine) as session:
        ds = session.get(DatasetStore, event_id)

    if ds is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    # Try to fetch from cloud object storage if image_path exists
    if ds.image_path:
        object_key = f"{event_id}.jpg"
        if _s3 and _s3.object_exists(object_key):
            image_bytes = _s3.get_object(object_key)
            if image_bytes is not None:
                return Response(
                    content=image_bytes,
                    media_type="image/jpeg",
                    headers={
                        "Content-Disposition": f'inline; filename="{event_id}.jpg"'
                    },
                )

    # Image not available yet – need to request upload from edge
    # We need camera_id and edge_id to build the command topic
    camera_id = ds.camera_id
    edge_id = _resolve_edge_id(camera_id)
    if edge_id is None:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot resolve edge_id for camera {camera_id}",
        )

    # Register a waiter for this upload
    upload_event = threading.Event()
    with _upload_lock:
        _upload_events[event_id] = upload_event

    try:
        # Publish upload command
        object_key = f"{event_id}.jpg"
        upload_url = (
            _s3.generate_presigned_upload_url(object_key)
            if _s3
            else f"{_cfg.object_storage_url}/{_cfg.s3_bucket}/{object_key}"
        )
        cmd_payload = {
            "event_id": event_id,
            "upload_url": upload_url,
        }
        cmd_topic = f"cloud/{edge_id}/{camera_id}/cmd/upload"
        _mqtt.publish(cmd_topic, cmd_payload, qos=1)
        log.info("Requested image upload: %s", cmd_topic)

        # Wait for upload_status to arrive (up to 30 seconds)
        completed = await asyncio.get_running_loop().run_in_executor(
            None, upload_event.wait, 30.0
        )
        if not completed:
            raise HTTPException(
                status_code=504,
                detail=f"Timeout waiting for image upload for event {event_id}",
            )

        # Re-read image_path from DB
        with get_session(_engine) as session:
            ds = session.get(DatasetStore, event_id)

        if ds is None or not ds.image_path:
            raise HTTPException(
                status_code=500,
                detail=f"Upload completed but image_path not set for {event_id}",
            )

        object_key = f"{event_id}.jpg"
        image_bytes = _s3.get_object(object_key) if _s3 else None
        if image_bytes is None:
            image_bytes = _try_fetch_image(ds.image_path)
        if image_bytes is None:
            raise HTTPException(
                status_code=502,
                detail=f"Could not fetch image from storage: {ds.image_path}",
            )

        return Response(
            content=image_bytes,
            media_type="image/jpeg",
            headers={"Content-Disposition": f'inline; filename="{event_id}.jpg"'},
        )
    finally:
        with _upload_lock:
            _upload_events.pop(event_id, None)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _try_fetch_image(url: str) -> bytes | None:
    """Try to GET an image from the given URL. Return bytes or None."""
    try:
        resp = http_requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
        log.warning("Image fetch %s returned HTTP %d", url, resp.status_code)
    except http_requests.RequestException as exc:
        log.warning("Image fetch %s failed: %s", url, exc)
    return None


def _resolve_edge_id(camera_id: str) -> str | None:
    """Look up the edge_id for a camera."""
    try:
        with get_session(_engine) as session:
            camera = session.get(Camera, camera_id)
            if camera:
                return camera.edge_id
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("Failed to resolve edge_id for camera %s", camera_id)
    return None
