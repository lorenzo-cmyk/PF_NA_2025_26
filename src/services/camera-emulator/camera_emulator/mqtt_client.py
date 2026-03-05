"""Thin wrapper around paho-mqtt v2 for the camera-emulator."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import paho.mqtt.client as mqtt

from camera_emulator.config import Config

log = logging.getLogger(__name__)
mqtt_log = logging.getLogger(f"{__name__}.events")


def _ts() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Type alias for the event-log callback registered by the web layer.
# (direction, topic, payload, operation_type, trigger, qos, retain)
LogCallback = Callable[[str, str, dict, str, str, int | None, bool | None], None]


class MQTTClient:  # pylint: disable=too-many-instance-attributes
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
        lwt_topic = f"{self._prefix}/telemetry"
        lwt_payload = json.dumps({"status": "offline"})
        self._client.will_set(
            topic=lwt_topic,
            payload=lwt_payload,
            qos=1,
            retain=True,
        )
        mqtt_log.info(
            "%s | LWT_SET | %s | QoS=1, Retained=True | "
            'payload={"status":"offline"} | trigger=Auto: MQTT client init',
            _ts(),
            lwt_topic,
        )

        # Internal state
        self._connected = False
        self._lock = threading.Lock()
        self._command_callbacks: list[Callable[[str, dict], None]] = []
        self._log_callbacks: list[LogCallback] = []
        self._pending_logs: list[tuple] = []
        self._connect_trigger: str | None = None

        # Buffer the LWT_SET event for the dashboard (no callbacks yet)
        self._pending_logs.append(
            (
                "SYSTEM",
                lwt_topic,
                {"status": "offline"},
                "LWT_SET",
                "Auto: MQTT client init",
                1,
                True,
            )
        )

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

    def start(self, trigger: str = "Auto: initial connect") -> None:
        """Connect and start the network loop in a background thread."""
        log.info(
            "Connecting to MQTT broker %s:%s …",
            self._cfg.mqtt_host,
            self._cfg.mqtt_port,
        )
        self._connect_trigger = trigger
        self._client.connect(self._cfg.mqtt_host, self._cfg.mqtt_port)
        self._client.loop_start()

    def stop(self) -> None:
        """Disconnect cleanly, then stop the network loop.

        Order matters: ``disconnect()`` sends the DISCONNECT packet while the
        background loop is still running so pending publishes (e.g. the
        offline telemetry) can be flushed first.
        """
        self._client.disconnect()
        self._client.loop_stop()

    def on_command(self, cb: Callable[[str, dict], None]) -> None:
        """Register a callback for incoming cmd/upload messages."""
        self._command_callbacks.append(cb)

    def on_log_event(self, cb: LogCallback) -> None:
        """Register a callback that receives structured log entries."""
        self._log_callbacks.append(cb)
        # Flush any events that were buffered before registration
        for entry in self._pending_logs:
            try:
                cb(*entry)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error replaying pending log")
        self._pending_logs.clear()

    # -- publishing helpers ------------------------------------------------ #

    def publish_birth(self, payload: dict[str, Any], trigger: str = "Unknown") -> None:
        """Publish a birth/registration message (retained)."""
        topic = f"{self._prefix}/lifecycle/birth"
        self._publish(topic, payload, qos=1, retain=True, trigger=trigger)

    def publish_telemetry(
        self, payload: dict[str, Any], trigger: str = "Unknown"
    ) -> None:
        """Publish a telemetry heartbeat (retained)."""
        topic = f"{self._prefix}/telemetry"
        self._publish(topic, payload, qos=1, retain=True, trigger=trigger)

    def publish_event(self, payload: dict[str, Any], trigger: str = "Unknown") -> None:
        """Publish an animal detection event."""
        topic = f"{self._prefix}/event"
        self._publish(topic, payload, qos=1, retain=False, trigger=trigger)

    def publish_upload_status(
        self, payload: dict[str, Any], trigger: str = "Unknown"
    ) -> None:
        """Publish an image upload status report."""
        topic = f"{self._prefix}/event/upload_status"
        self._publish(topic, payload, qos=1, retain=False, trigger=trigger)

    # -- internal ---------------------------------------------------------- #

    def _publish(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        topic: str,
        payload: dict,
        qos: int = 1,
        retain: bool = False,
        trigger: str = "Unknown",
    ) -> None:
        data = json.dumps(payload)
        info = self._client.publish(topic, data, qos=qos, retain=retain)
        mqtt_log.info(
            "%s | PUBLISH | %s | QoS=%d, Retained=%s | RC=%s | trigger=%s",
            _ts(),
            topic,
            qos,
            retain,
            info.rc,
            trigger,
        )
        self._emit_log("OUT", topic, payload, "PUBLISH", trigger, qos, retain)

    def _emit_log(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        direction: str,
        topic: str,
        payload: dict,
        operation: str,
        trigger: str,
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        """Forward a structured log entry to all registered callbacks."""
        for cb in self._log_callbacks:
            try:
                cb(direction, topic, payload, operation, trigger, qos, retain)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error in log callback")

    def _on_connect(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        rc: Any,
        _properties: Any = None,
    ) -> None:
        trigger = self._connect_trigger or "Auto: connected"
        self._connect_trigger = None
        mqtt_log.info(
            "%s | CONNECT | broker=%s:%s | RC=%s | trigger=%s",
            _ts(),
            self._cfg.mqtt_host,
            self._cfg.mqtt_port,
            rc,
            trigger,
        )
        with self._lock:
            self._connected = True
        self._emit_log(
            "SYSTEM",
            f"{self._cfg.mqtt_host}:{self._cfg.mqtt_port}",
            {"rc": str(rc)},
            "CONNECT",
            trigger,
        )
        # Subscribe to incoming upload commands
        cmd_topic = f"{self._prefix}/cmd/upload"
        client.subscribe(cmd_topic, qos=1)
        mqtt_log.info(
            "%s | SUBSCRIBE | %s | QoS=1 | trigger=Auto: on_connect",
            _ts(),
            cmd_topic,
        )
        self._emit_log(
            "SYSTEM",
            cmd_topic,
            {},
            "SUBSCRIBE",
            "Auto: on_connect",
            qos=1,
        )

    def _on_disconnect(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        rc: Any,
        _properties: Any = None,
    ) -> None:
        graceful = str(rc) == "Normal disconnection"
        trigger = (
            "Manual: graceful disconnect"
            if graceful
            else "LWT: Ungraceful disconnect detected"
        )
        mqtt_log.info(
            "%s | DISCONNECT | broker=%s:%s | RC=%s | trigger=%s",
            _ts(),
            self._cfg.mqtt_host,
            self._cfg.mqtt_port,
            rc,
            trigger,
        )
        with self._lock:
            self._connected = False
        self._emit_log(
            "SYSTEM",
            f"{self._cfg.mqtt_host}:{self._cfg.mqtt_port}",
            {"rc": str(rc)},
            "DISCONNECT",
            trigger,
        )

    def _on_message(
        self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": msg.payload.decode(errors="replace")}

        summary_parts = []
        if "event_id" in payload:
            summary_parts.append(f"event_id={payload['event_id']}")
        if "upload_url" in payload:
            summary_parts.append(f"url={payload['upload_url']}")
        summary = " | ".join(summary_parts) if summary_parts else str(msg.payload[:200])

        mqtt_log.info(
            "%s | RECEIVED | %s | QoS=%d, Retained=%s | %s | trigger=Received cmd/upload from broker",
            _ts(),
            msg.topic,
            msg.qos,
            bool(msg.retain),
            summary,
        )
        self._emit_log(
            "IN",
            msg.topic,
            payload,
            "RECEIVED",
            "Received cmd/upload from broker",
            qos=msg.qos,
            retain=bool(msg.retain),
        )

        for cb in self._command_callbacks:
            try:
                cb(msg.topic, payload)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error in command callback")
