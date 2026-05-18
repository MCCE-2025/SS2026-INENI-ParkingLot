# Parking Lot — AWS CDK Infrastructure

Python CDK app that provisions the cloud-side resources for the parking-lot
detector:

- IoT Thing + X.509 device certificate (private key stored in Secrets Manager)
- IoT policy (MQTT publish + named Device Shadow `occupancy`)
- IoT Topic Rule: `parkinglot/+/status` → DynamoDB (`SELECT *` persists `source`, `device_id`, etc.)
- DynamoDB table `ParkingLotEvents` (`lot_id` + `ts` keys)

The device code in `../parking_lot/` is unchanged; this stack matches its
existing MQTT topic layout and CLI flags. Install device dependencies from the
repo root with `uv sync` (see the main `README.md`).

## Prerequisites

- AWS account with credentials configured (`aws configure` or environment variables)
- [Node.js](https://nodejs.org/) (for the `cdk` CLI): `npm install -g aws-cdk`
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Python 3.10+ (uv can install one via `uv python install 3.12`)

## Setup

```bash
cd infra
uv sync --all-groups
```

This creates `.venv/` and installs CDK libraries plus dev tools (`boto3` for
`fetch_certs.py`). `cdk.json` is configured to run the app via `uv run`, so
`cdk synth` / `cdk deploy` use the same environment automatically.

## Deploy

Bootstrap CDK once per account/region:

```bash
cdk bootstrap
```

Deploy the stack:

```bash
cdk deploy
```

Tunable values live in `cdk.json` → `context`:

| Key | Default |
|-----|---------|
| `thing_name` | `parking_lot_camera_01` |
| `lot_id` | `lot_1` |
| `shadow_name` | `occupancy` |
| `events_table_name` | `ParkingLotEvents` |

## Fetch device certificates

After deploy, materialize cert files for the Python device CLI:

```bash
uv run python scripts/fetch_certs.py --stack ParkingLotStack --output ../certs
```

This writes `device.pem.crt`, `private.pem.key`, and `AmazonRootCA1.pem` under
`../certs/` (gitignored) and prints an example `main.py` command.

## Build simulator command

To assemble a full `simulator.py` CLI (IoT flags from stack outputs, cert paths
from `../certs/`, smoke-test defaults for `--spots` / `--interval` / `--max-events`):

```bash
uv run python scripts/build_simulator_cmd.py --stack ParkingLotStack --certs ../certs
```

Use `--list-required` to print mandatory IoT flags; use `--one-line` for a
single-line command. See the root [`README.md`](../README.md) simulator section.

## Verify in AWS

1. Open **IoT Core → MQTT test client**, subscribe to `parkinglot/#`.
2. Run the simulator from `../parking_lot/` using the command from
   `build_simulator_cmd.py` (or the flags printed by `fetch_certs.py`).
3. Check **DynamoDB → ParkingLotEvents** for new items after status events.

## Web dashboard stack

`ParkingLotWebStack` (registered in `app.py` alongside `ParkingLotStack`) provisions:

- S3 + CloudFront SPA hosting
- Cognito Identity Pool (unauthenticated) with **read-only** IoT subscribe policy
- HTTP API:
  - `GET /snapshot` — GetSnapshot Lambda (Device Shadow, DynamoDB fallback)
  - `GET /history` — GetHistory Lambda (DynamoDB time-range query)
  - `POST /control` — Control Lambda (publish `parkinglot/<lot_id>/status` with `source: "web"` + update named shadow)
- Runtime `config.json` injected at deploy time

The Control Lambda needs `iot:Publish` on the status topic and `iot:UpdateThingShadow` on the Thing, including the **named shadow** IAM resource (`arn:...:thing/<thing>/<shadowName>`). See `_thing_shadow_iam_resources()` in `parking_lot_cdk/parking_lot_web_stack.py`.

Deploy after building the frontend:

```bash
uv run python scripts/deploy_web.py
```

Or manually:

```bash
cd ../web && npm install && npm run build
cd ../infra && cdk deploy ParkingLotWebStack
```

Outputs: `WebUrl`, `ApiUrl`, `IdentityPoolId`.

## Teardown

```bash
cdk destroy --all
```

Destroy `ParkingLotWebStack` alone to iterate on the frontend without touching device certs:

```bash
cdk destroy ParkingLotWebStack
```

Because the stack uses `RemovalPolicy.DESTROY` on the DynamoDB table and
Secrets Manager secret, destroy removes those resources (after emptying the
table where required).

## Construct notes

- **L2 stable**: `dynamodb.Table`, `secretsmanager.Secret`, `iam.Role`,
  `iam.PolicyDocument`, `lambda.Function`, `custom_resources.Provider`,
  `AwsCustomResource`
- **L1** (no stable L2): `CfnThing`, `CfnPolicy`, `CfnTopicRule`, attachments
- No `aws-cdk.aws-iot-alpha` packages
- Device certificate creation and Secrets Manager population are performed
  by an inline Python Lambda (`CertificateProvisionerFunction`) fronted by
  `custom_resources.Provider`. Doing this in a single Lambda avoids the
  CloudFormation JSON-string interpolation bug that occurs when PEM
  newlines from `createKeysAndCertificate` are fed into an
  `AwsCustomResource` parameter built with `Stack.to_json_string`.

## Legacy `requirements.txt`

`requirements.txt` and `requirements-dev.txt` are kept for reference; prefer
`pyproject.toml` and `uv sync` for installs.
