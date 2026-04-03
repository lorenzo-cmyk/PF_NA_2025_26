"""MQTT client for the WatchEdge camera service."""

from __future__ import annotations

import json
import logging
import random
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import paho.mqtt.client as mqtt

from camera.config import Config

log = logging.getLogger(__name__)
mqtt_log = logging.getLogger(f"{__name__}.events")


def _ts() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Type alias: (direction, topic, payload, operation_type, trigger, qos, retain)
LogCallback = Callable[[str, str, dict, str, str, int | None, bool | None], None]


class MQTTClient:  # pylint: disable=too-many-instance-attributes
    """Manages MQTT connection, LWT, birth, telemetry, events, and upload commands."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._prefix = cfg.topic_prefix()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.mqtt_client_id or None,
        )

        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

        # LWT — broker publishes this if we disconnect ungracefully
        lwt_topic = f"{self._prefix}/telemetry"
        lwt_payload = json.dumps({"status": "Offline"})
        self._client.will_set(lwt_topic, lwt_payload, qos=1, retain=True)
        mqtt_log.info(
            "%s | LWT_SET | %s | QoS=1, Retained=True | trigger=Auto: MQTT client init",
            _ts(),
            lwt_topic,
        )

        self._connected = False
        self._lock = threading.Lock()
        self._command_callbacks: list[Callable[[str, dict], None]] = []
        self._log_callbacks: list[LogCallback] = []
        self._pending_logs: list[tuple] = []
        self._connect_trigger: str | None = None

        self._pending_logs.append(
            (
                "SYSTEM",
                lwt_topic,
                {"status": "Offline"},
                "LWT_SET",
                "Auto: MQTT client init",
                1,
                True,
            )
        )

        self._telemetry_thread: threading.Thread | None = None
        self._telemetry_stop = threading.Event()

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # -- public API -------------------------------------------------------- #

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def is_connected(self) -> bool:
        return self.connected

    def start(self, trigger: str = "Auto: initial connect") -> None:
        """Connect to broker, start the network loop, and begin telemetry heartbeat."""
        log.info(
            "Connecting to MQTT broker %s:%s …",
            self._cfg.mqtt_host,
            self._cfg.mqtt_port,
        )
        self._connect_trigger = trigger
        self._client.connect(self._cfg.mqtt_host, self._cfg.mqtt_port)
        self._client.loop_start()
        self._start_telemetry_loop()

    def stop(self) -> None:
        """Publish an offline telemetry message, then disconnect cleanly."""
        self._stop_telemetry_loop()
        # Best-effort graceful offline publish
        try:
            self.publish_telemetry(
                payload={"timestamp": _ts(), "status": "Offline"},
                trigger="Manual: shutdown",
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        self._client.disconnect()
        self._client.loop_stop()

    def on_command(self, cb: Callable[[str, dict], None]) -> None:
        """Register a callback for incoming ``cmd/upload`` messages."""
        self._command_callbacks.append(cb)

    def on_log_event(self, cb: LogCallback) -> None:
        """Register a callback that receives structured log entries."""
        self._log_callbacks.append(cb)
        for entry in self._pending_logs:
            try:
                cb(*entry)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Error replaying pending log entry")
        self._pending_logs.clear()

    # -- publishing -------------------------------------------------------- #

    def publish_birth(
        self,
        payload: dict | None = None,
        trigger: str = "Auto: on_connect",
    ) -> None:
        """Publish the retained birth/registration message.

        Uses ``payload`` if provided; otherwise derives values from config.
        """
        topic = f"{self._prefix}/lifecycle/birth"
        self._publish(
            topic,
            payload if payload is not None else self._cfg.birth_payload(),
            qos=1,
            retain=True,
            trigger=trigger,
        )

    def publish_telemetry(
        self,
        payload: dict | None = None,
        trigger: str = "Auto: heartbeat",
    ) -> None:
        """Publish a retained telemetry heartbeat.

        If *payload* is provided it is published as-is; otherwise the payload
        is built from hardware sensors (or placeholder values).
        """
        if payload is None:
            payload = {
                "timestamp": _ts(),
                "status": "Online",
                "temperature": self._read_temperature(),
                "battery_level": self._read_battery(),
            }
        topic = f"{self._prefix}/telemetry"
        self._publish(topic, payload, qos=1, retain=True, trigger=trigger)

    def publish_event(self, payload: dict[str, Any], trigger: str = "Unknown") -> None:
        """Publish a detection event."""
        topic = f"{self._prefix}/event"
        self._publish(topic, payload, qos=1, retain=False, trigger=trigger)

    def publish_upload_status(self, event_id: str, status: str, detail: str) -> None:
        """Publish upload result.

        ``status`` is ``"SUCCESS"`` or ``"ERROR"``.
        On success, ``detail`` is the ``remote_path``.
        On error, ``detail`` is the error ``message``.
        """
        if status == "SUCCESS":
            payload: dict[str, Any] = {
                "event_id": event_id,
                "status": "SUCCESS",
                "remote_path": detail,
            }
        else:
            payload = {
                "event_id": event_id,
                "status": "ERROR",
                "message": detail,
            }
        topic = f"{self._prefix}/event/upload_status"
        self._publish(
            topic,
            payload,
            qos=1,
            retain=False,
            trigger=f"Auto: upload result {event_id}",
        )

    # -- telemetry loop ---------------------------------------------------- #

    def _start_telemetry_loop(self) -> None:
        self._telemetry_stop.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop, daemon=True, name="telemetry"
        )
        self._telemetry_thread.start()

    def _stop_telemetry_loop(self) -> None:
        self._telemetry_stop.set()
        if self._telemetry_thread is not None:
            self._telemetry_thread.join(timeout=5.0)
            self._telemetry_thread = None

    def _telemetry_loop(self) -> None:
        while not self._telemetry_stop.wait(timeout=self._cfg.telemetry_interval_s):
            if self.connected:
                try:
                    self.publish_telemetry()
                except Exception:  # pylint: disable=broad-exception-caught
                    log.exception("Telemetry publish failed.")

    # -- hardware stubs ---------------------------------------------------- #

    @staticmethod
    def _read_temperature() -> float:
        """Read CPU/ambient temperature if available, otherwise return a placeholder."""
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", encoding="utf-8") as f:
                return round(int(f.read().strip()) / 1000.0, 1)
        except OSError:
            return round(random.uniform(15.0, 35.0), 1)

    @staticmethod
    def _read_battery() -> int:
        """Read battery level (0-100) if available, otherwise return 100."""
        try:
            with open("/sys/class/power_supply/BAT0/capacity", encoding="utf-8") as f:
                return int(f.read().strip())
        except OSError:
            return 100

    # -- internal ---------------------------------------------------------- #

    def _publish(
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
        # Subscribe to upload commands
        cmd_topic = f"{self._prefix}/cmd/upload"
        client.subscribe(cmd_topic, qos=1)
        mqtt_log.info(
            "%s | SUBSCRIBE | %s | QoS=1 | trigger=Auto: on_connect",
            _ts(),
            cmd_topic,
        )
        self._emit_log("SYSTEM", cmd_topic, {}, "SUBSCRIBE", "Auto: on_connect", qos=1)
        # Auto-publish birth on every (re)connect
        self.publish_birth(trigger="Auto: on_connect")

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
        except (json.JSONDecodeError, UnicodeDecodeError):  # fmt: skip
            payload = {"raw": msg.payload.decode(errors="replace")}

        parts = []
        if "event_id" in payload:
            parts.append(f"event_id={payload['event_id']}")
        if "upload_url" in payload:
            parts.append(f"url={payload['upload_url']}")
        summary = " | ".join(parts) if parts else str(msg.payload[:200])

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
