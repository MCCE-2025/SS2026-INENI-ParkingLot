# Architecture Diagram

```mermaid
flowchart TB
    %% ── DEVICE SIDE ─────────────────────────────────────────────────────────
    subgraph DEVICE["Edge Device (Raspberry Pi / PC)"]
        direction TB
        CAM["📷 Webcam / Video File"]
        MD["Motion Detector\n(OpenCV · Laplacian edge detection)"]
        SIM["Simulator\n(synthetic occupancy events)"]
        IOT_PUB["IoT Publisher\n(awsiot · MQTT + Device Shadow)"]
        DDB_PUB["DynamoDB Publisher\n(direct sink for local testing)"]

        CAM -->|frames| MD
        MD -->|spot state changes| IOT_PUB
        SIM -->|spot state changes| IOT_PUB
        SIM -->|local testing| DDB_PUB
    end

    %% ── AWS CLOUD ────────────────────────────────────────────────────────────
    subgraph AWS["AWS Cloud"]

        subgraph INFRA["ParkingLotStack  (CDK)"]
            direction TB

            subgraph IOT["AWS IoT Core"]
                BROKER["MQTT Broker\n(port 8883 · X.509 mTLS)"]
                SHADOW["Device Shadow\n(named: occupancy)"]
                RULE["Topic Rule\nparkinglot/+/status\n→ DynamoDBv2 action"]
            end

            DDB[("DynamoDB\nParkingLotEvents\nPK: lot_id  SK: ts")]
            SM["Secrets Manager\n(device cert + private key)"]
            CERT_LAMBDA["Cert Provisioner Lambda\n(Custom Resource · one-time)"]

            CERT_LAMBDA -->|CreateKeysAndCertificate| BROKER
            CERT_LAMBDA -->|store JSON| SM
            BROKER -->|per-spot status msgs| RULE
            RULE -->|PutItem| DDB
            BROKER <-->|shadow updates / reads| SHADOW
        end

        subgraph WEB_STACK["ParkingLotWebStack  (CDK)"]
            direction TB

            subgraph HOSTING["Static Hosting"]
                CF["CloudFront CDN"]
                S3["S3 Bucket\n(React SPA dist/)"]
                CF -->|Origin Access Control| S3
            end

            COGNITO["Cognito Identity Pool\n(unauthenticated)\ntemp AWS credentials"]

            subgraph API["HTTP API  (API Gateway v2)"]
                SNAP["GET /snapshot\nGetSnapshot Lambda\n(Device Shadow → DynamoDB fallback)"]
                HIST["GET /history\nGetHistory Lambda\n(1-hour DynamoDB query)"]
                CTRL["POST /control\nControl Lambda\n(MQTT publish + shadow update)"]
            end

            SNAP -->|GetThingShadow| SHADOW
            SNAP -->|fallback Query| DDB
            HIST -->|Query by lot_id + ts range| DDB
            CTRL -->|Publish parkinglot/lot_id/status| BROKER
            CTRL -->|UpdateThingShadow| SHADOW
        end
    end

    %% ── BROWSER ──────────────────────────────────────────────────────────────
    subgraph BROWSER["Browser  (React SPA · Vite)"]
        direction TB

        subgraph LIBS["lib/"]
            COGN_LIB["cognito.ts\nGetId · GetCredentials"]
            SIGV4["sigv4.ts\nSigV4 presigned WSS URL"]
            MQTT_LIB["mqtt.ts\nMQTT.js over WSS"]
            API_LIB["api.ts\nHTTP fetch client"]
        end

        APP["App.tsx\n(state reducer)"]

        subgraph UI["Components"]
            TILES["SummaryTiles\nfree / occupied counts"]
            GRID["SpotGrid\nclick to toggle · manual badge\n(green = free · blue = occupied)"]
            SPARK["SparklineHistory\n15-min chart\ndevice + manual lines"]
            PILL["ConnectionPill\nMQTT status badge"]
        end

        COGN_LIB --> SIGV4
        SIGV4 --> MQTT_LIB
        APP --> COGN_LIB
        APP --> MQTT_LIB
        APP --> API_LIB
        APP --> UI
    end

    %% ── CROSS-BOUNDARY CONNECTIONS ───────────────────────────────────────────
    IOT_PUB -->|"X.509 mTLS · MQTT\nparkinglot/lot_id/status\nparkinglot/lot_id/summary\n$aws/things/.../shadow/..."| BROKER
    DDB_PUB -->|PutItem| DDB

    BROWSER -->|HTTPS| CF
    COGN_LIB -->|GetId · GetCredentialsForIdentity| COGNITO
    MQTT_LIB -->|"SigV4 presigned WSS\nport 443\nSubscribe: parkinglot/#"| BROKER
    API_LIB -->|"GET /snapshot\nGET /history\nPOST /control"| API
    GRID -->|"POST spot_id, occupied"| API_LIB

    %% ── STYLING ──────────────────────────────────────────────────────────────
    classDef aws      fill:#FF9900,color:#000,stroke:#c47700
    classDef lambda   fill:#FF9900,color:#000,stroke:#c47700,stroke-dasharray:4
    classDef dynamo   fill:#4053D6,color:#fff,stroke:#2d3ab5
    classDef iot      fill:#1A9C3E,color:#fff,stroke:#127a30
    classDef web      fill:#0078D4,color:#fff,stroke:#005fa3
    classDef device   fill:#6C4A9E,color:#fff,stroke:#4e3572
    classDef browser  fill:#E8F4FD,color:#000,stroke:#0078D4

    class BROKER,SHADOW,RULE iot
    class DDB dynamo
    class CF,S3,COGNITO,API aws
    class SNAP,HIST,CTRL,CERT_LAMBDA lambda
    class SM aws
    class CAM,MD,SIM,IOT_PUB,DDB_PUB device
    class APP,COGN_LIB,SIGV4,MQTT_LIB,API_LIB,TILES,GRID,SPARK,PILL browser
```

## Component Overview

| Layer | Component | Role |
|-------|-----------|------|
| **Edge** | Motion Detector | OpenCV + Laplacian edge detection to classify each parking spot as free/occupied |
| **Edge** | Simulator | Generates synthetic occupancy events for testing without a camera |
| **Edge** | IoT Publisher | Sends per-spot status via MQTT + keeps Device Shadow up-to-date |
| **IoT Core** | MQTT Broker | Receives device messages over TLS 1.3 with X.509 mutual auth |
| **IoT Core** | Device Shadow | Stores the latest full occupancy snapshot (named shadow: `occupancy`) |
| **IoT Core** | Topic Rule | Fans per-spot status messages into DynamoDB via a DynamoDBv2 action |
| **DynamoDB** | ParkingLotEvents | Time-series event log (PK: `lot_id`, SK: `ts`) with TTL for auto-expiry |
| **Lambda** | GetSnapshot | Returns Device Shadow; falls back to DynamoDB reconstruction if shadow unavailable |
| **Lambda** | GetHistory | Queries DynamoDB for a time window to bootstrap the sparkline (default 1 hour in Lambda; UI queries 15 minutes) |
| **Lambda** | Control | Manual overrides: publishes `source: "web"` to `parkinglot/<lot_id>/status` and updates the Device Shadow (`device_id: web_control`) |
| **Cognito** | Identity Pool | Issues temporary AWS credentials to anonymous browser users |
| **CloudFront + S3** | Static Hosting | Serves the React SPA globally with OAC-protected S3 origin |
| **Browser** | React SPA | Displays live spot grid, summary tiles, and sparkline via MQTT + HTTP API |
| **Browser** | mqtt.ts | MQTT.js over SigV4-presigned WSS — subscribes to live status + summary topics (read-only) |
| **Browser** | SpotGrid | Click a spot → `POST /control`; manual spots show badge when `source === "web"` |
| **Browser** | SparklineHistory | Dual series: device (solid) vs manual (dashed); history appended on each status event |

## Status event shape

Every `parkinglot/<lot_id>/status` message (device or web) includes:

| Field | Device example | Web (manual) example |
|-------|----------------|----------------------|
| `lot_id` | `lot_1` | `lot_1` |
| `spot_id` | `2` | `2` |
| `occupied` | `true` | `false` |
| `ts` | ISO 8601 UTC | ISO 8601 UTC |
| `device_id` | `parking_lot_camera_01` | `web_control` |
| `source` | `device` | `web` |

The topic rule `SELECT *` writes all fields to DynamoDB. Per-spot entries in the Device Shadow also carry `source` when updated.

## Key Data Flows

```
Device (source: device) → IoT Core → DynamoDB     (event log via Topic Rule)
Device → IoT Core Device Shadow                     (latest snapshot)
Browser → Cognito → SigV4 → MQTT WSS               (subscribe-only live updates)
Browser → GET /snapshot, /history → Lambda          (initial load)
Browser → POST /control → Control Lambda            (source: web → MQTT + Shadow)
Control → MQTT → Topic Rule → DynamoDB              (manual rows with source: web)
Control → MQTT → browsers                           (grid + sparkline via applyStatus)
Browser appends status events to local history       (sparkline updates without refetch)
```
