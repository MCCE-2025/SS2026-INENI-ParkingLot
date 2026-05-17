"""AWS IoT Core publisher (MQTT + Device Shadow).

Optional integration for the parking-lot detector. When constructed, this
module connects to AWS IoT Core over MQTT (TLS 8883, X.509 mTLS) and:

* Publishes per-spot state-change events to ``parkinglot/<lot_id>/status``.
* Publishes periodic occupancy summaries to ``parkinglot/<lot_id>/summary``.
* Mirrors live occupancy in a named Device Shadow (default: ``occupancy``).

Network I/O is non-blocking: the AWS CRT runs publishes on its own thread
and failures are logged rather than raised into the detector loop.
"""

import json
import logging
import time

from awscrt import mqtt
from awsiot import iotshadow, mqtt_connection_builder

logger = logging.getLogger(__name__)


def add_iot_args(parser):
    """Register the AWS IoT Core argument group on *parser*."""
    iot_group = parser.add_argument_group(
        "AWS IoT Core",
        "Optional MQTT + Device Shadow integration. All --iot-* flags "
        "except --iot-endpoint are ignored unless --iot-endpoint is set.",
    )
    iot_group.add_argument(
        "--iot-endpoint",
        dest="iot_endpoint",
        default=None,
        help=(
            "AWS IoT Core data endpoint (from "
            "`aws iot describe-endpoint --endpoint-type iot:Data-ATS`). "
            "Enables MQTT publishing when set."
        ),
    )
    iot_group.add_argument(
        "--iot-client-id",
        dest="iot_client_id",
        default=None,
        help="MQTT client ID and IoT Thing name (required with --iot-endpoint).",
    )
    iot_group.add_argument(
        "--iot-cert",
        dest="iot_cert",
        default=None,
        help="Path to device certificate PEM (required with --iot-endpoint).",
    )
    iot_group.add_argument(
        "--iot-key",
        dest="iot_key",
        default=None,
        help="Path to device private key PEM (required with --iot-endpoint).",
    )
    iot_group.add_argument(
        "--iot-ca",
        dest="iot_ca",
        default=None,
        help="Path to Amazon Root CA PEM (required with --iot-endpoint).",
    )
    iot_group.add_argument(
        "--iot-lot-id",
        dest="iot_lot_id",
        default="lot_1",
        help="Parking lot identifier used in MQTT topics. Default: lot_1.",
    )
    iot_group.add_argument(
        "--iot-shadow-name",
        dest="iot_shadow_name",
        default="occupancy",
        help="Named Device Shadow to update. Default: occupancy.",
    )
    iot_group.add_argument(
        "--iot-summary-interval",
        dest="iot_summary_interval",
        type=float,
        default=30.0,
        help=(
            "Seconds between periodic summary heartbeats on MQTT and in the "
            "shadow. Default: 30."
        ),
    )


def build_iot_publisher(args, required=False):
    """Construct an :class:`IoTPublisher` from parsed CLI *args*.

    When *required* is True, ``--iot-endpoint`` must be set or the process
    exits. When *required* is False (default), a missing endpoint returns
    ``None`` so the detector can run without AWS IoT.
    """
    if args.iot_endpoint is None:
        if required:
            raise SystemExit(
                "AWS IoT Core is required but --iot-endpoint was not provided."
            )
        return None

    missing = []
    if not args.iot_client_id:
        missing.append("--iot-client-id")
    if not args.iot_cert:
        missing.append("--iot-cert")
    if not args.iot_key:
        missing.append("--iot-key")
    if not args.iot_ca:
        missing.append("--iot-ca")
    if missing:
        raise SystemExit(
            "AWS IoT Core is enabled via --iot-endpoint but the following "
            "required flags are missing: %s" % ", ".join(missing)
        )

    logger.info(
        "Connecting to AWS IoT Core (endpoint=%s, client_id=%s, lot_id=%s).",
        args.iot_endpoint,
        args.iot_client_id,
        args.iot_lot_id,
    )
    return IoTPublisher(
        endpoint=args.iot_endpoint,
        client_id=args.iot_client_id,
        cert_path=args.iot_cert,
        key_path=args.iot_key,
        ca_path=args.iot_ca,
        lot_id=args.iot_lot_id,
        shadow_name=args.iot_shadow_name,
        summary_interval=args.iot_summary_interval,
    )


def _utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _summary_from_statuses(statuses):
    """Build {free, occupied, total} from detector statuses.

    In MotionDetector, ``status=True`` means the spot is empty (low Laplacian).
    """
    free = sum(1 for s in statuses if s)
    total = len(statuses)
    return {"free": free, "occupied": total - free, "total": total}


class IoTPublisher:
    """Publish parking occupancy to AWS IoT Core via MQTT and Device Shadow."""

    def __init__(
        self,
        endpoint,
        client_id,
        cert_path,
        key_path,
        ca_path,
        lot_id="lot_1",
        shadow_name="occupancy",
        summary_interval=30.0,
    ):
        self.lot_id = lot_id
        self.client_id = client_id
        self.shadow_name = shadow_name
        self.summary_interval = float(summary_interval)
        self._last_summary_time = 0.0
        self._initial_snapshot_sent = False

        self._connection = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint,
            cert_filepath=cert_path,
            pri_key_filepath=key_path,
            ca_filepath=ca_path,
            client_id=client_id,
            clean_session=False,
            keep_alive_secs=30,
            on_connection_interrupted=self._on_connection_interrupted,
            on_connection_resumed=self._on_connection_resumed,
        )
        connect_future = self._connection.connect()
        connect_future.result()
        logger.info(
            "Connected to AWS IoT Core at %s as client %s",
            endpoint,
            client_id,
        )

        self._shadow_client = iotshadow.IotShadowClient(self._connection)

    def publish_spot(self, spot_id, occupied, statuses=None, ts=None):
        """Publish a confirmed spot state change (MQTT + shadow delta)."""
        ts = ts or _utc_timestamp()
        payload = {
            "lot_id": self.lot_id,
            "spot_id": int(spot_id),
            "occupied": bool(occupied),
            "ts": ts,
            "device_id": self.client_id,
        }
        topic = "parkinglot/%s/status" % self.lot_id
        self._publish_json(topic, payload)

        shadow_reported = {
            "lot_id": self.lot_id,
            "device_id": self.client_id,
            "spots": {
                str(spot_id): {"occupied": bool(occupied), "ts": ts},
            },
            "ts": ts,
        }
        if statuses is not None:
            shadow_reported["summary"] = _summary_from_statuses(statuses)
        self._update_shadow_reported(shadow_reported)

    def publish_initial_snapshot(self, statuses):
        """Publish full occupancy state after the first detection pass."""
        if self._initial_snapshot_sent:
            return
        self._initial_snapshot_sent = True

        ts = _utc_timestamp()
        spots = {}
        for index, status in enumerate(statuses):
            spots[str(index)] = {
                "occupied": not bool(status),
                "ts": ts,
            }

        summary = _summary_from_statuses(statuses)
        shadow_reported = {
            "lot_id": self.lot_id,
            "device_id": self.client_id,
            "spots": spots,
            "summary": summary,
            "ts": ts,
        }
        self._update_shadow_reported(shadow_reported)
        logger.info(
            "Published initial shadow snapshot for %d spots (%s)",
            len(statuses),
            summary,
        )

    def publish_summary_if_due(self, statuses, now):
        """Publish a periodic summary heartbeat if the interval has elapsed."""
        if now - self._last_summary_time < self.summary_interval:
            return

        self._last_summary_time = now
        ts = _utc_timestamp()
        summary = _summary_from_statuses(statuses)
        payload = {
            "lot_id": self.lot_id,
            "device_id": self.client_id,
            "ts": ts,
            **summary,
        }
        topic = "parkinglot/%s/summary" % self.lot_id
        self._publish_json(topic, payload)

        shadow_reported = {
            "summary": summary,
            "ts": ts,
        }
        self._update_shadow_reported(shadow_reported)
        logger.debug("Published summary heartbeat: %s", summary)

    def disconnect(self):
        """Disconnect from AWS IoT Core."""
        try:
            disconnect_future = self._connection.disconnect()
            disconnect_future.result()
            logger.info("Disconnected from AWS IoT Core")
        except Exception as exc:
            logger.warning("Error disconnecting from AWS IoT Core: %s", exc)

    def _publish_json(self, topic, payload):
        try:
            future, _packet_id = self._connection.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            future.add_done_callback(self._log_publish_result(topic))
        except Exception as exc:
            logger.warning("Failed to publish to %s: %s", topic, exc)

    def _update_shadow_reported(self, reported):
        try:
            request = iotshadow.UpdateNamedShadowRequest(
                thing_name=self.client_id,
                shadow_name=self.shadow_name,
                state=iotshadow.ShadowState(reported=reported),
            )
            future = self._shadow_client.publish_update_named_shadow(
                request,
                mqtt.QoS.AT_LEAST_ONCE,
            )
            future.add_done_callback(
                self._log_shadow_result("update", self.shadow_name)
            )
        except Exception as exc:
            logger.warning(
                "Failed to update shadow %r: %s",
                self.shadow_name,
                exc,
            )

    @staticmethod
    def _log_publish_result(topic):
        def callback(future):
            try:
                future.result()
            except Exception as exc:
                logger.warning("MQTT publish to %s failed: %s", topic, exc)

        return callback

    @staticmethod
    def _log_shadow_result(operation, shadow_name):
        def callback(future):
            try:
                future.result()
            except Exception as exc:
                logger.warning(
                    "Shadow %s on %r failed: %s",
                    operation,
                    shadow_name,
                    exc,
                )

        return callback

    @staticmethod
    def _on_connection_interrupted(connection, error, **kwargs):
        logger.warning("MQTT connection interrupted: %s", error)

    @staticmethod
    def _on_connection_resumed(connection, return_code, session_present, **kwargs):
        logger.info(
            "MQTT connection resumed (return_code=%s, session_present=%s)",
            return_code,
            session_present,
        )
