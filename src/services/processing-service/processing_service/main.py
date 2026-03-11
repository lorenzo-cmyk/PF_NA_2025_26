"""Processing Service – entry point.

Starts the MQTT client and FastAPI server.
Operates as Edge or Cloud depending on SERVICE_MODE.
"""

from __future__ import annotations

import logging
import signal
import sys

import uvicorn

from processing_service.config import Config
from processing_service.database import get_engine
from processing_service.handlers import MessageHandler
from processing_service.mqtt_client import MQTTClient
from processing_service.s3_client import S3Client
from processing_service import api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def main() -> None:
    """Boot the processing service: MQTT client + HTTP server."""
    cfg = Config()
    cfg.log()

    # Database
    engine = get_engine(cfg.database_url)

    # Object Storage (S3)
    s3: S3Client | None = None
    try:
        s3 = S3Client(cfg)
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("Failed to initialise S3 client – image features disabled")

    # MQTT
    mqtt = MQTTClient(cfg)

    # Message handler
    handler = MessageHandler(cfg, mqtt, engine, s3)

    # For cloud mode, hook upload-status notifications into the API layer
    if cfg.is_cloud:
        _original_upload_status = handler.handle_upload_status

        def _upload_status_with_notification(payload):
            _original_upload_status(payload)
            event_id = payload.get("event_id")
            status = payload.get("status", "").upper()
            if event_id and status == "SUCCESS":
                api.notify_upload_complete(event_id)

        handler.handle_upload_status = _upload_status_with_notification

    # Register message handler
    mqtt.on_message(handler.handle)

    # Configure subscriptions based on mode
    if cfg.is_edge:
        mqtt.add_subscription("edge/#")
        mqtt.add_subscription("cloud/+/+/cmd/upload")
        log.info("EDGE mode: subscribing to edge/# and cloud/+/+/cmd/upload")
    else:
        mqtt.add_subscription("cloud/#")
        log.info("CLOUD mode: subscribing to cloud/#")

    # Wire up the API module
    api.init(cfg, mqtt, engine, s3)

    # Graceful shutdown handler
    def _shutdown(sig: int, _frame: object) -> None:
        log.info("Shutting down (signal %s)…", signal.Signals(sig).name)
        mqtt.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Start MQTT
    try:
        mqtt.start()
    except OSError:
        log.exception(
            "Could not connect to MQTT broker – HTTP server will start anyway"
        )

    # Start HTTP
    log.info("HTTP server → http://%s:%s", cfg.web_host, cfg.web_port)
    uvicorn.run(
        api.app,
        host=cfg.web_host,
        port=cfg.web_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
