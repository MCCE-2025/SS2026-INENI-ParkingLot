"""API Lambda: return occupancy snapshot (Device Shadow, with DynamoDB fallback)."""

import decimal
import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

_CORS = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
}


def _empty_shadow(lot_id, device_id=""):
    return {
        "state": {
            "reported": {
                "lot_id": lot_id,
                "device_id": device_id,
                "spots": {},
                "summary": {"free": 0, "occupied": 0, "total": 0},
                "ts": _utc_now(),
            }
        }
    }


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iot_data_client():
    endpoint = os.environ.get("IOT_DATA_ENDPOINT", "").strip()
    region = os.environ.get("AWS_REGION", "eu-central-1")
    if endpoint:
        if not endpoint.startswith("https://"):
            endpoint = "https://%s" % endpoint
        return boto3.client("iot-data", endpoint_url=endpoint, region_name=region)
    return boto3.client("iot-data", region_name=region)


def _spot_key(spot_id):
    if isinstance(spot_id, decimal.Decimal):
        spot_id = int(spot_id) if spot_id % 1 == 0 else float(spot_id)
    return str(int(spot_id))


def _snapshot_from_dynamodb(table_name, lot_id, device_id):
    """Rebuild latest per-spot state from status events (newest ts wins)."""
    table = boto3.resource("dynamodb").Table(table_name)
    to_ts = _utc_now()
    from_ts = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    spots = {}
    latest_ts = to_ts
    response = table.query(
        KeyConditionExpression=Key("lot_id").eq(lot_id)
        & Key("ts").between(from_ts, to_ts),
        ScanIndexForward=False,
        Limit=2000,
    )
    for item in response.get("Items", []):
        key = _spot_key(item.get("spot_id", 0))
        if key in spots:
            continue
        occupied = bool(item.get("occupied", False))
        ts = item.get("ts", to_ts)
        spots[key] = {"occupied": occupied, "ts": ts}
        if ts > latest_ts:
            latest_ts = ts

    occupied_count = sum(1 for s in spots.values() if s["occupied"])
    total = len(spots)
    summary = {
        "free": total - occupied_count,
        "occupied": occupied_count,
        "total": total,
    }
    return {
        "state": {
            "reported": {
                "lot_id": lot_id,
                "device_id": device_id,
                "spots": spots,
                "summary": summary,
                "ts": latest_ts,
            }
        },
        "_source": "dynamodb",
    }


def _try_shadow():
    thing = os.environ["THING_NAME"]
    shadow = os.environ.get("SHADOW_NAME", "").strip()
    kwargs = {"thingName": thing}
    if shadow:
        kwargs["shadowName"] = shadow
    body = _iot_data_client().get_thing_shadow(**kwargs)["payload"].read()
    return json.loads(body.decode("utf-8"))


def handler(event, context):
    del event, context
    lot_id = os.environ.get("LOT_ID", "lot_1")
    device_id = os.environ.get("DEVICE_ID", os.environ.get("THING_NAME", ""))
    table_name = os.environ.get("TABLE_NAME", "").strip()

    try:
        doc = _try_shadow()
        return {
            "statusCode": 200,
            "headers": _CORS,
            "body": json.dumps(doc),
        }
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ResourceNotFoundException", "404"):
            doc = _empty_shadow(lot_id, device_id)
            return {
                "statusCode": 200,
                "headers": _CORS,
                "body": json.dumps(doc),
            }
        if table_name and code in ("ForbiddenException", "Forbidden"):
            doc = _snapshot_from_dynamodb(table_name, lot_id, device_id)
            return {
                "statusCode": 200,
                "headers": _CORS,
                "body": json.dumps(doc),
            }
        return {
            "statusCode": 502,
            "headers": _CORS,
            "body": json.dumps({"error": str(exc), "code": code}),
        }
    except Exception as exc:
        if table_name:
            doc = _snapshot_from_dynamodb(table_name, lot_id, device_id)
            return {
                "statusCode": 200,
                "headers": _CORS,
                "body": json.dumps(doc),
            }
        return {
            "statusCode": 502,
            "headers": _CORS,
            "body": json.dumps({"error": str(exc)}),
        }
