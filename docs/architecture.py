"""
Parking Lot Detector — Architecture Diagram
Requires: pip install diagrams
Run:      python docs/architecture.py
Output:   docs/architecture.png
"""

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import DynamodbTable
from diagrams.aws.iot import IotRule, IotShadow, IotMqtt, IotCamera, IotSimulator
from diagrams.aws.network import CloudFront, APIGateway
from diagrams.aws.security import Cognito, SecretsManager
from diagrams.aws.storage import S3
from diagrams.onprem.client import User
from diagrams.generic.os import Raspbian

GRAPH_ATTR = {
    "fontsize": "18",
    "bgcolor": "white",
    "pad": "0.6",
    "splines": "ortho",
    "nodesep": "0.9",
    "ranksep": "1.4",
}

EDGE_MQTT   = Edge(color="#1a9c3e", style="bold",   label="MQTT / mTLS\n(port 8883)")
EDGE_WSS    = Edge(color="#1a9c3e", style="dashed",  label="MQTT / WSS\n(SigV4)")
EDGE_HTTP   = Edge(color="#0078d4", style="solid",   label="HTTPS")
EDGE_CREDS  = Edge(color="#c47700", style="dotted",  label="temp credentials")
EDGE_RULE   = Edge(color="#6c4a9e", style="bold",    label="DynamoDBv2 action")
EDGE_SHADOW = Edge(color="#1a9c3e", style="dashed",  label="shadow update")
EDGE_PLAIN  = Edge(color="#555555", style="solid")
EDGE_QUERY  = Edge(color="#555555", style="solid",   label="Query")
EDGE_CERT   = Edge(color="#d13212", style="dotted",  label="store cert")
EDGE_CTRL   = Edge(color="#0078d4", style="bold",    label="POST /control")
EDGE_PUB    = Edge(color="#1a9c3e", style="bold",    label="Publish status")

with Diagram(
    "Parking Lot Detector — Architecture",
    filename="docs/architecture",
    outformat="png",
    show=False,
    graph_attr=GRAPH_ATTR,
    direction="TB",
):
    # ── Edge Device ───────────────────────────────────────────────────────────
    with Cluster("Edge Device"):
        camera   = IotCamera("Webcam / Video")
        detector = Raspbian("Motion Detector\n(OpenCV · Laplacian)")
        sim      = IotSimulator("Simulator\n(synthetic events)")
        camera >> EDGE_PLAIN >> detector

    # ── Browser ───────────────────────────────────────────────────────────────
    with Cluster("Browser (React SPA)"):
        browser = User("Viewer")

    # ── AWS Cloud ─────────────────────────────────────────────────────────────
    with Cluster("AWS Cloud"):

        # ── IoT Core ─────────────────────────────────────────────────────────
        with Cluster("AWS IoT Core  (ParkingLotStack)"):
            broker = IotMqtt("MQTT Broker\n(port 8883 · mTLS)")
            shadow = IotShadow("Device Shadow\n(named: occupancy)")
            rule   = IotRule("Topic Rule\nparkinglot/+/status")

        # ── Cert provisioning ─────────────────────────────────────────────────
        with Cluster("Certificate Provisioning  (ParkingLotStack)"):
            cert_fn = Lambda("Cert Provisioner\n(Custom Resource)")
            sm      = SecretsManager("Secrets Manager\n(device cert + key)")
            cert_fn >> EDGE_CERT >> sm

        # ── DynamoDB — shared data layer ──────────────────────────────────────
        with Cluster("Data  (ParkingLotStack)"):
            ddb = DynamodbTable("ParkingLotEvents\nPK: lot_id  SK: ts")

        # ── Web stack — API ───────────────────────────────────────────────────
        with Cluster("API  (ParkingLotWebStack)"):
            cognito = Cognito("Cognito Identity Pool\n(unauthenticated)")
            apigw    = APIGateway("HTTP API\n(API Gateway v2)")
            snap_fn  = Lambda("GetSnapshot\n(shadow + DDB fallback)")
            hist_fn  = Lambda("GetHistory\n(1-hour DDB query)")
            ctrl_fn  = Lambda("Control\n(MQTT publish + shadow)")

        # ── Web stack — Hosting ───────────────────────────────────────────────
        with Cluster("Static Hosting  (ParkingLotWebStack)"):
            cf = CloudFront("CloudFront CDN")
            s3 = S3("S3 Bucket\n(React SPA)")
            cf >> EDGE_PLAIN >> s3

    # ── Edges — Device → IoT Core ─────────────────────────────────────────────
    detector >> EDGE_MQTT >> broker
    sim      >> EDGE_MQTT >> broker

    # ── Edges — IoT Core internal ─────────────────────────────────────────────
    broker >> EDGE_RULE   >> rule
    broker >> EDGE_SHADOW >> shadow

    # ── Edges — Topic Rule → DynamoDB ─────────────────────────────────────────
    rule >> EDGE_PLAIN >> ddb

    # ── Edges — Cert provisioning ─────────────────────────────────────────────
    cert_fn >> Edge(color="#d13212", style="dotted",
                    label="CreateKeysAndCertificate") >> broker

    # ── Edges — API Lambdas ───────────────────────────────────────────────────
    apigw    >> EDGE_PLAIN >> snap_fn
    apigw    >> EDGE_PLAIN >> hist_fn
    apigw    >> EDGE_PLAIN >> ctrl_fn
    snap_fn  >> Edge(color="#1a9c3e", style="dashed",
                     label="GetThingShadow")     >> shadow
    snap_fn  >> Edge(color="#555555", style="dotted",
                     label="fallback Query")     >> ddb
    hist_fn  >> EDGE_QUERY                        >> ddb
    ctrl_fn  >> EDGE_PUB                          >> broker
    ctrl_fn  >> EDGE_SHADOW                       >> shadow

    # ── Edges — Browser ───────────────────────────────────────────────────────
    browser >> EDGE_HTTP  >> cf
    browser >> EDGE_CREDS >> cognito
    browser >> EDGE_WSS   >> broker
    browser >> EDGE_HTTP  >> apigw
    browser >> EDGE_CTRL  >> apigw
