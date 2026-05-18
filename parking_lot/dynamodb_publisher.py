"""Direct DynamoDB publisher for the parking-lot simulator.

Writes per-spot status events with the same item shape that the AWS IoT Topic
Rule persists (``parkinglot/+/status`` → DynamoDB ``ParkingLotEvents``).
Intended for local testing against DynamoDB Local without AWS IoT Core.
"""

import logging
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "ParkingLotEvents"
_DEFAULT_REGION = "eu-central-1"
_DEFAULT_LOT_ID = "lot_1"
_DEFAULT_DEVICE_ID = "parking_lot_camera_01"


def add_dynamodb_args(parser):
    """Register the local DynamoDB sink argument group on *parser*."""
    ddb_group = parser.add_argument_group(
        "Local DynamoDB sink",
        "Direct PutItem to DynamoDB (e.g. DynamoDB Local). Used when "
        "--sink dynamodb; --iot-* flags are ignored in that mode.",
    )
    ddb_group.add_argument(
        "--dynamodb-endpoint",
        dest="dynamodb_endpoint",
        default=None,
        help=(
            "DynamoDB API endpoint URL (e.g. http://localhost:8000 for "
            "DynamoDB Local). Required when --sink dynamodb."
        ),
    )
    ddb_group.add_argument(
        "--dynamodb-table",
        dest="dynamodb_table",
        default=_DEFAULT_TABLE,
        help="Events table name. Default: %s." % _DEFAULT_TABLE,
    )
    ddb_group.add_argument(
        "--dynamodb-region",
        dest="dynamodb_region",
        default=_DEFAULT_REGION,
        help=(
            "AWS region for boto3 (DynamoDB Local ignores it). "
            "Default: %s." % _DEFAULT_REGION
        ),
    )
    ddb_group.add_argument(
        "--dynamodb-lot-id",
        dest="dynamodb_lot_id",
        default=_DEFAULT_LOT_ID,
        help="Parking lot identifier in stored items. Default: %s." % _DEFAULT_LOT_ID,
    )
    ddb_group.add_argument(
        "--dynamodb-device-id",
        dest="dynamodb_device_id",
        default=_DEFAULT_DEVICE_ID,
        help=(
            "Device identifier in stored items (device_id field). "
            "Default: %s." % _DEFAULT_DEVICE_ID
        ),
    )


def build_dynamodb_publisher(args, required=False):
    """Construct a :class:`DynamodbPublisher` from parsed CLI *args*.

    When *required* is True, ``--dynamodb-endpoint`` must be set or the process
    exits. When *required* is False, a missing endpoint returns ``None``.
    """
    if args.dynamodb_endpoint is None:
        if required:
            raise SystemExit(
                "DynamoDB sink is required but --dynamodb-endpoint was not provided."
            )
        return None

    logger.info(
        "Connecting to DynamoDB (endpoint=%s, table=%s, lot_id=%s).",
        args.dynamodb_endpoint,
        args.dynamodb_table,
        args.dynamodb_lot_id,
    )
    return DynamodbPublisher(
        endpoint_url=args.dynamodb_endpoint,
        table_name=args.dynamodb_table,
        region_name=args.dynamodb_region,
        lot_id=args.dynamodb_lot_id,
        device_id=args.dynamodb_device_id,
    )


def _utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _create_table_hint(table_name, region):
    return (
        "aws dynamodb create-table \\\n"
        "  --table-name %s \\\n"
        "  --attribute-definitions "
        "AttributeName=lot_id,AttributeType=S "
        "AttributeName=ts,AttributeType=S \\\n"
        "  --key-schema AttributeName=lot_id,KeyType=HASH "
        "AttributeName=ts,KeyType=RANGE \\\n"
        "  --billing-mode PAY_PER_REQUEST \\\n"
        "  --region %s \\\n"
        "  --endpoint-url <your-dynamodb-endpoint>"
        % (table_name, region)
    )


def _ensure_table_exists(resource, table_name, region_name, endpoint_url):
    """Verify the table exists; exit with a helpful message if not."""
    client = resource.meta.client
    try:
        client.describe_table(TableName=table_name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            raise SystemExit(
                "DynamoDB table %r not found at endpoint %s.\n"
                "Create it first, for example:\n\n%s"
                % (table_name, endpoint_url, _create_table_hint(table_name, region_name))
            ) from exc
        raise


class DynamodbPublisher:
    """Write parking occupancy status events directly to DynamoDB."""

    def __init__(
        self,
        endpoint_url,
        table_name=_DEFAULT_TABLE,
        region_name=_DEFAULT_REGION,
        lot_id=_DEFAULT_LOT_ID,
        device_id=_DEFAULT_DEVICE_ID,
    ):
        self.lot_id = lot_id
        self.device_id = device_id
        self._resource = boto3.resource(
            "dynamodb",
            endpoint_url=endpoint_url,
            region_name=region_name,
        )
        _ensure_table_exists(self._resource, table_name, region_name, endpoint_url)
        self._table = self._resource.Table(table_name)
        logger.info(
            "DynamoDB publisher ready (table=%s, endpoint=%s).",
            table_name,
            endpoint_url,
        )

    def publish_spot(self, spot_id, occupied, statuses=None, ts=None):
        """Persist one status event (same fields as MQTT status payload)."""
        ts = ts or _utc_timestamp()
        item = {
            "lot_id": self.lot_id,
            "ts": ts,
            "spot_id": int(spot_id),
            "occupied": bool(occupied),
            "device_id": self.device_id,
            "source": "device",
        }
        try:
            self._table.put_item(Item=item)
            logger.debug("Wrote status event to DynamoDB: %s", item)
        except ClientError as exc:
            logger.warning("Failed to put_item to DynamoDB: %s", exc)

    def publish_initial_snapshot(self, statuses):
        """Log initial occupancy only (cloud rule does not write snapshots)."""
        free = sum(1 for s in statuses if s)
        total = len(statuses)
        logger.info(
            "Initial snapshot (not written to DynamoDB): %d free, %d occupied "
            "of %d spots.",
            free,
            total - free,
            total,
        )

    def publish_summary_if_due(self, statuses, now):
        """No-op for DynamoDB (cloud rule does not persist summary heartbeats)."""
        return

    def disconnect(self):
        """No persistent connection to close."""
        logger.info("DynamoDB publisher finished.")
