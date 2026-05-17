"""API Lambda: query ParkingLotEvents for a lot and time window."""

import decimal
import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 == 0:
                return int(o)
            return float(o)
        return super().default(o)


def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_from():
    return (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def handler(event, context):
    del context
    params = event.get("queryStringParameters") or {}
    lot_id = params.get("lot_id") or os.environ.get("DEFAULT_LOT_ID", "lot_1")
    from_ts = params.get("from") or _default_from()
    to_ts = params.get("to") or _iso_now()

    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    response = table.query(
        KeyConditionExpression=Key("lot_id").eq(lot_id)
        & Key("ts").between(from_ts, to_ts),
        Limit=2000,
    )
    items = response.get("Items", [])
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(
            {"items": items, "count": len(items)},
            cls=_DecimalEncoder,
        ),
    }
