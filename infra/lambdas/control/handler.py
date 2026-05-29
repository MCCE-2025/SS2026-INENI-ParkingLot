"""API Lambda: publish spot status to MQTT and update Device Shadow."""

import base64
import json
import os

import boto3
from botocore.exceptions import ClientError

from _timestamps import event_timestamps

_CORS = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
}


def _iot_data_client():
    endpoint = os.environ.get("IOT_DATA_ENDPOINT", "").strip()
    region = os.environ.get("AWS_REGION", "eu-central-1")
    if endpoint:
        if not endpoint.startswith("https://"):
            endpoint = "https://%s" % endpoint
        return boto3.client("iot-data", endpoint_url=endpoint, region_name=region)
    return boto3.client("iot-data", region_name=region)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": _CORS,
        "body": json.dumps(body),
    }


def _parse_body(event):
    raw = event.get("body")
    if raw is None or raw == "":
        return None
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def _summary_from_spots(spots):
    total = len(spots)
    occupied = sum(1 for spot in spots.values() if spot.get("occupied"))
    return {"free": total - occupied, "occupied": occupied, "total": total}


def _get_reported_spots(client, thing_name, shadow_name):
    kwargs = {"thingName": thing_name}
    if shadow_name:
        kwargs["shadowName"] = shadow_name
    try:
        payload = client.get_thing_shadow(**kwargs)["payload"].read()
        doc = json.loads(payload.decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ResourceNotFoundException", "404"):
            return {}
        raise
    reported = doc.get("state", {}).get("reported", {})
    spots = reported.get("spots")
    if not isinstance(spots, dict):
        return {}
    return spots


def _validate_body(body):
    if not isinstance(body, dict):
        return None, "Request body must be a JSON object"

    if "spot_id" not in body:
        return None, "Missing required field: spot_id"
    if "occupied" not in body:
        return None, "Missing required field: occupied"

    try:
        spot_id = int(body["spot_id"])
    except (TypeError, ValueError):
        return None, "spot_id must be an integer"

    occupied = body["occupied"]
    if not isinstance(occupied, bool):
        return None, "occupied must be a boolean"

    source = body.get("source", "web")
    if source not in ("web", "truth"):
        return None, "source must be 'web' or 'truth'"

    return {"spot_id": spot_id, "occupied": occupied, "source": source}, None


def handler(event, context):
    del context

    try:
        body = _parse_body(event)
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if body is None:
        return _response(400, {"error": "Missing request body"})

    validated, err = _validate_body(body)
    if err:
        return _response(400, {"error": err})

    lot_id = os.environ.get("LOT_ID", "lot_1")
    thing_name = os.environ["THING_NAME"]
    shadow_name = os.environ.get("SHADOW_NAME", "").strip()
    source = validated["source"]
    if source == "truth":
        device_id = os.environ.get("CONTROL_TRUTH_DEVICE_ID", "truth_capture")
    else:
        device_id = os.environ.get("CONTROL_DEVICE_ID", "web_control")

    spot_id = validated["spot_id"]
    occupied = validated["occupied"]
    ts, epoch = event_timestamps()

    status_payload = {
        "lot_id": lot_id,
        "spot_id": spot_id,
        "occupied": occupied,
        "ts": ts,
        "epoch": int(epoch),
        "device_id": device_id,
        "source": source,
    }
    topic = "parkinglot/%s/status" % lot_id

    client = _iot_data_client()

    try:
        client.publish(
            topic=topic,
            qos=1,
            payload=json.dumps(status_payload),
        )
    except ClientError as exc:
        return _response(
            500,
            {
                "error": "Failed to publish status",
                "code": exc.response.get("Error", {}).get("Code", ""),
            },
        )

    if source == "web":
        try:
            spots = _get_reported_spots(client, thing_name, shadow_name)
        except ClientError as exc:
            return _response(
                500,
                {
                    "error": "Published status but failed to read shadow",
                    "code": exc.response.get("Error", {}).get("Code", ""),
                },
            )

        spots = dict(spots)
        spots[str(spot_id)] = {"occupied": occupied, "ts": ts, "source": "web"}
        summary = _summary_from_spots(spots)

        summary_payload = {
            "lot_id": lot_id,
            "device_id": device_id,
            "ts": ts,
            **summary,
        }
        summary_topic = "parkinglot/%s/summary" % lot_id

        try:
            client.publish(
                topic=summary_topic,
                qos=1,
                payload=json.dumps(summary_payload),
            )
        except ClientError as exc:
            return _response(
                500,
                {
                    "error": "Published status but failed to publish summary",
                    "code": exc.response.get("Error", {}).get("Code", ""),
                },
            )

        shadow_reported = {
            "lot_id": lot_id,
            "device_id": device_id,
            "spots": {
                str(spot_id): {"occupied": occupied, "ts": ts, "source": "web"},
            },
            "summary": summary,
            "ts": ts,
        }
        shadow_payload = json.dumps({"state": {"reported": shadow_reported}})
        shadow_kwargs = {"thingName": thing_name, "payload": shadow_payload}
        if shadow_name:
            shadow_kwargs["shadowName"] = shadow_name

        try:
            client.update_thing_shadow(**shadow_kwargs)
        except ClientError as exc:
            return _response(
                500,
                {
                    "error": "Published status and summary but failed to update shadow",
                    "code": exc.response.get("Error", {}).get("Code", ""),
                },
            )

    return _response(
        200,
        {"ok": True, "ts": ts, "spot_id": spot_id, "occupied": occupied, "source": source},
    )
