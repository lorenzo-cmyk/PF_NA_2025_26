"""Thin wrapper around paho-mqtt v2 for the Processing Service."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import paho.mqtt.client as mqtt

from processing_service.config import Config

log = logging.getLogger(__name__)

# Type alias for message callbacks: (topic, payload_dict)
MessageCallback = Callable[[str, dict[str, Any]], None]


class MQTTClient:
    """Manages MQTT connection, subscriptions, publishing."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.mqtt_client_id,
        )

        # Internal state
        self._connected = False
        self._lock = threading.Lock()
        self._message_callbacks: list[MessageCallback] = []

        # Wire paho callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Topics to subscribe on connect
        self._subscriptions: list[str] = []

    # -- public API -------------------------------------------------------- #

    @property
    def connected(self) -> bool:
        """Return True when connected to the MQTT broker."""
        with self._lock:
            return self._connected

    def add_subscription(self, topic: str) -> None:
        """Register a topic pattern to subscribe to on connect."""
        self._subscriptions.append(topic)

    def on_message(self, cb: MessageCallback) -> None:
        """Register a callback for all incoming messages."""
        self._message_callbacks.append(cb)

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
        """Disconnect cleanly, then stop the network loop."""
        self._client.disconnect()
        self._client.loop_stop()

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a JSON payload to the given topic."""
        data = json.dumps(payload)
        info = self._client.publish(topic, data, qos=qos, retain=retain)
        log.info(
            "PUBLISH %s (QoS=%d, retain=%s, rc=%s)",
            topic,
            qos,
            retain,
            info.rc,
        )

    # -- paho callbacks ---------------------------------------------------- #

    def _on_connect(
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
        # Subscribe to configured topics
        for topic in self._subscriptions:
            client.subscribe(topic, qos=1)
            log.info("SUBSCRIBE %s (QoS=1)", topic)

    def _on_disconnect(
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
        try:
            payload: dict[str, Any] = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("Non-JSON payload on %s – skipping", msg.topic)
            return

        log.debug(
            "RECEIVED %s (QoS=%d, retain=%s)",
            msg.topic,
            msg.qos,
            bool(msg.retain),
        )

        for cb in self._message_callbacks:
            try:
                cb(msg.topic, payload)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error in message callback for %s", msg.topic)
