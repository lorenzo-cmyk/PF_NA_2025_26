"""Thin wrapper around paho-mqtt v2 for the camera-emulator."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import paho.mqtt.client as mqtt

from camera_emulator.config import Config

log = logging.getLogger(__name__)


class MQTTClient:
    """Manages MQTT connection, publishing, subscribing, and LWT."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._prefix = cfg.topic_prefix()

        # paho v2 API
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.mqtt_client_id,
        )

        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

        # LWT: if we disconnect ungracefully, the broker publishes this
        lwt_payload = json.dumps({"status": "offline"})
        self._client.will_set(
            topic=f"{self._prefix}/telemetry",
            payload=lwt_payload,
            qos=1,
            retain=True,
        )

        # Internal state
        self._connected = False
        self._lock = threading.Lock()
        self._command_callbacks: list[Callable[[str, dict], None]] = []

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # -- public API -------------------------------------------------------- #

    @property
    def connected(self) -> bool:
        """Return ``True`` if the MQTT client is currently connected."""
        with self._lock:
            return self._connected

    def start(self) -> None:
        """Connect and start the network loop in a background thread."""
        log.info(
            "Connecting to MQTT broker %s:%s …",
            self._cfg.mqtt_host,
            self._cfg.mqtt_port,
        )
        self._client.connect(self._cfg.mqtt_host, self._cfg.mqtt_port)
        self._client.loop_start()

    def stop(self) -> None:
        """Stop the network loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()

    def on_command(self, cb: Callable[[str, dict], None]) -> None:
        """Register a callback for incoming cmd/upload messages."""
        self._command_callbacks.append(cb)

    # -- publishing helpers ------------------------------------------------ #

    def publish_birth(self, payload: dict[str, Any]) -> None:
        """Publish a birth/registration message (retained)."""
        topic = f"{self._prefix}/lifecycle/birth"
        self._publish(topic, payload, qos=1, retain=True)

    def publish_telemetry(self, payload: dict[str, Any]) -> None:
        """Publish a telemetry heartbeat (retained)."""
        topic = f"{self._prefix}/telemetry"
        self._publish(topic, payload, qos=1, retain=True)

    def publish_event(self, payload: dict[str, Any]) -> None:
        """Publish an animal detection event."""
        topic = f"{self._prefix}/event"
        self._publish(topic, payload, qos=1)

    def publish_upload_status(self, payload: dict[str, Any]) -> None:
        """Publish an image upload status report."""
        topic = f"{self._prefix}/event/upload_status"
        self._publish(topic, payload, qos=1)

    # -- internal ---------------------------------------------------------- #

    def _publish(
        self, topic: str, payload: dict, qos: int = 1, retain: bool = False
    ) -> None:
        data = json.dumps(payload)
        info = self._client.publish(topic, data, qos=qos, retain=retain)
        log.info("PUB %s  (rc=%s)", topic, info.rc)

    def _on_connect(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        rc: Any,
        _properties: Any = None,
    ) -> None:
        log.info("Connected to MQTT broker (rc=%s)", rc)
        with self._lock:
            self._connected = True
        # Subscribe to incoming upload commands
        cmd_topic = f"{self._prefix}/cmd/upload"
        client.subscribe(cmd_topic, qos=1)
        log.info("SUB %s", cmd_topic)

    def _on_disconnect(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        rc: Any,
        _properties: Any = None,
    ) -> None:
        log.warning("Disconnected from MQTT broker (rc=%s)", rc)
        with self._lock:
            self._connected = False

    def _on_message(
        self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        log.info("MSG %s  %s", msg.topic, msg.payload[:200])
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": msg.payload.decode(errors="replace")}
        for cb in self._command_callbacks:
            try:
                cb(msg.topic, payload)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error in command callback")
