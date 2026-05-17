# Agent guide — Parking Lot Detector

Overview for AI agents and developers working in this repository.

## What this project is

OpenCV-based parking-space occupancy detection: the user marks quadrilateral regions on a still frame, then the app classifies each region as **empty** (green overlay) or **occupied** (blue overlay) using Laplacian edge variance inside a mask.

Extended on the `webcam` / `iot-core-mqtt` branches with:

- Live **webcam** input and V4L2 hardware controls
- Optional **AWS IoT Core** publishing (MQTT + named Device Shadow)
- A **simulator** that fakes occupancy events without a camera
- **CDK infrastructure** (`infra/`) to provision Thing, certificate, policy, DynamoDB sink

Original upstream: [olgarose/ParkingLot](https://github.com/olgarose/ParkingLot) (weekend OpenCV experiment).

## Repository layout

```
.
├── AGENT.md                 # This file
├── README.md                # User-facing docs (OpenCV walkthrough + IoT + simulator)
├── pyproject.toml           # Device/runtime deps (uv); OpenCV app in parking_lot/
├── uv.lock                  # Locked device dependencies
├── parking_lot/             # Application code (run from this directory)
│   ├── main.py              # CLI entry: marking + detection
│   ├── motion_detector.py   # Per-frame Laplacian occupancy loop
│   ├── coordinates_generator.py  # Interactive spot marking (mouse)
│   ├── iot_publisher.py     # AWS IoT MQTT + Device Shadow (optional)
│   ├── simulator.py         # Synthetic events → IoTPublisher (no OpenCV)
│   ├── webcam_controls.py   # V4L2-style camera properties + auto-brightness
│   ├── drawing_utils.py, colors.py
│   ├── data/                # YAML spot coordinates (often gitignored via data/)
│   ├── images/, videos/     # Sample assets
│   └── tests/               # Minimal / placeholder tests
└── infra/                   # AWS CDK (Python, uv-managed)
    ├── app.py
    ├── cdk.json             # app: "uv run python app.py"
    ├── pyproject.toml       # CDK + boto3 (dev group)
    ├── parking_lot_cdk/parking_lot_stack.py
    └── scripts/fetch_certs.py
```

## Branches

| Branch | Notes |
|--------|--------|
| `master` | Original video-file-only detector |
| `webcam` | Webcam input, marking UX, hardware controls |
| `iot-core-mqtt` | Webcam + AWS IoT publisher + simulator + `infra/` CDK |

Prefer **`iot-core-mqtt`** (or `webcam` if IoT is out of scope) for current work.

## Critical semantics (easy to get wrong)

In `motion_detector.py`, internal `status=True` means the spot is **empty** (low Laplacian variance inside the mask). The UI uses green for empty, blue for occupied.

`IoTPublisher` reports cloud-friendly `occupied = not status`.

Debouncing: a change must hold for `--detect-delay` seconds (default 1.0) before `statuses[]` updates and IoT publishes fire.

## Running the application

Install device deps from the repo root (`uv sync`), then work from `parking_lot/`:

```bash
# Install device deps (repo root)
uv sync

# Webcam, auto-mark if data file empty
uv run python main.py --video 0 --data data/coordinates_webcam.yml

# Video file
uv run python main.py --video videos/parking_lot_1.mp4 --data data/coordinates_1.yml --start-frame 400

# With AWS IoT (after infra deploy + fetch_certs)
uv run python main.py --video 0 --data data/coordinates_webcam.yml \
  --iot-endpoint <endpoint> --iot-client-id parking_lot_camera_01 \
  --iot-cert ../certs/device.pem.crt --iot-key ../certs/private.pem.key \
  --iot-ca ../certs/AmazonRootCA1.pem

# Simulator (no camera)
uv run python simulator.py --spots 8 --interval 3 --max-events 10 \
  --iot-endpoint ... --iot-client-id ... --iot-cert ... --iot-key ... --iot-ca ...
```

IoT flags are defined in `iot_publisher.add_iot_args()` and built via `build_iot_publisher(args)`. Omit `--iot-endpoint` to disable cloud publishing entirely.

## AWS IoT contract (device ↔ cloud)

| Item | Value |
|------|--------|
| MQTT topics | `parkinglot/<lot_id>/status`, `parkinglot/<lot_id>/summary` |
| Shadow name | `occupancy` (default, `--iot-shadow-name`) |
| Thing name | Same as `--iot-client-id` (default `parking_lot_camera_01`) |
| Status payload | `{lot_id, spot_id, occupied, ts, device_id}` |

See `README.md` for example policy JSON and shadow document shape.

## Infrastructure (`infra/`)

Python CDK stack provisions: IoT Thing, cert (via custom resource → Secrets Manager), IoT policy, topic rule `parkinglot/+/status` → DynamoDB `ParkingLotEvents` (`lot_id` + `ts` keys).

**Tooling:** [uv](https://docs.astral.sh/uv/) for device app (`uv sync` at repo root) and CDK (`cd infra && uv sync`). See `infra/README.md`.

```bash
cd infra
uv sync --all-groups
aws configure          # requires AWS CLI on the host
cdk bootstrap
cdk deploy
uv run python scripts/fetch_certs.py --stack ParkingLotStack --output ../certs
```

**Construct mix:** L2 for DynamoDB, Secrets Manager, IAM, `AwsCustomResource`; L1 for `CfnThing`, `CfnPolicy`, `CfnTopicRule` (no stable L2; alpha packages intentionally avoided).

Tunables in `infra/cdk.json` → `context`: `thing_name`, `lot_id`, `shadow_name`, `events_table_name`.

## Gitignored / secrets

Never commit: `certs/`, `*.pem`, `*.key`, `*.crt`, `.venv/`, `infra/cdk.out/`, `infra/.venv/`, `data/` (coordinates may contain site-specific layouts).

## Conventions for agents

- **Scope:** Only change files required by the task. Do not refactor unrelated OpenCV code.
- **IoT optional:** `main.py` and `simulator.py` must run without `awsiotsdk` connectivity when `--iot-endpoint` is omitted (import of `iot_publisher` still loads the module; connection is lazy at `build_iot_publisher`).
- **Shared IoT CLI:** Add or change `--iot-*` flags only in `iot_publisher.add_iot_args()`, not duplicated in `main.py` / `simulator.py`.
- **Policy parity:** IoT policy in CDK (`parking_lot_stack.py`) must stay aligned with `README.md` so console/manual and CDK paths behave the same.
- **Tests:** `parking_lot/tests/` is minimal; prefer not to add heavy test harnesses unless asked.
- **Commits:** Only commit when the user explicitly requests it.

## Common tasks

| Task | Where to look |
|------|----------------|
| Fix false occupancy flicker | `motion_detector.py` — `LAPLACIAN`, `DETECT_DELAY`, CLI `--laplacian`, `--detect-delay` |
| Webcam black frames on Linux | `main.py` `_capture_frame`, `motion_detector._warmup_capture` |
| IoT publish on state change | `motion_detector.py` after `statuses[index] = status` |
| Cloud provisioning | `infra/parking_lot_cdk/parking_lot_stack.py` |
| Test cloud without camera | `parking_lot/simulator.py` |
| Materialize device certs | `infra/scripts/fetch_certs.py` |

## Dependencies

| Area | Install |
|------|---------|
| Device app | `uv sync` (repo root) — `opencv-python`, `numpy`, `PyYAML`, `awsiotsdk` |
| CDK / infra | `cd infra && uv sync --all-groups` |
| CLI tools | AWS CLI (`aws configure`), Node.js + `npm install -g aws-cdk` |

## Further reading

- `README.md` — user documentation, IoT setup, simulator
- `infra/README.md` — deploy, destroy, uv workflow
