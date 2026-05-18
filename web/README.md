# Parking Lot Web Dashboard

React + Vite SPA for real-time occupancy. Deployed by `ParkingLotWebStack` (S3 + CloudFront + API Gateway + Cognito Identity Pool).

## Features

- **Summary tiles** — free / occupied counts and last update time
- **Spot grid** — click a spot to toggle occupied/free via `POST /control`; green = free, blue = occupied (matches the OpenCV overlay)
- **Manual overrides** — spots updated from the dashboard show a **manual** badge and dashed outline (`source: "web"` in MQTT/DynamoDB)
- **Sparkline** — last 15 minutes of occupancy; solid line = device events, dashed line = manual overrides
- **Live MQTT** — subscribe-only WSS connection (SigV4 + Cognito); grid and history update on each status message

## Prerequisites

- Node.js 20+
- `ParkingLotStack` and `ParkingLotWebStack` deployed (`infra/scripts/deploy_web.py`)
- Optional: simulator or detector publishing to AWS IoT for live tiles

## Local development

1. Deploy the web stack once so API and Cognito exist:

   ```bash
   cd infra
   uv run python scripts/deploy_web.py
   ```

2. Create `public/config.json` from the example (gitignored):

   ```bash
   cp public/config.example.json public/config.json
   ```

   Fill in values from CloudFormation outputs (`WebUrl` is not needed locally; use `ApiUrl`, `IdentityPoolId`, and `IoTDataEndpoint` from `ParkingLotStack` / `ParkingLotWebStack`):

   ```json
   {
     "region": "eu-central-1",
     "iotEndpoint": "<IoTDataEndpoint from ParkingLotStack>",
     "identityPoolId": "<IdentityPoolId from ParkingLotWebStack>",
     "apiUrl": "<ApiUrl from ParkingLotWebStack>",
     "lotId": "lot_1",
     "thingName": "parking_lot_camera_01",
     "shadowName": "occupancy"
   }
   ```

3. Install and run the dev server:

   ```bash
   npm install
   npm run dev
   ```

   Open http://localhost:5173. The dev server serves `public/config.json`; API and IoT calls go to AWS (CORS allows `localhost:5173`).

## HTTP API (used by the SPA)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/snapshot` | Initial occupancy from Device Shadow |
| `GET` | `/history?lot_id=&from=&to=` | Event log for sparkline bootstrap |
| `POST` | `/control` | Manual override: `{ "spot_id": number, "occupied": boolean }` |

Manual control publishes `source: "web"` and `device_id: "web_control"`. Device/simulator events use `source: "device"` and the Thing name as `device_id`.

## Production build

```bash
npm run build
```

Output is in `dist/`. Redeploy with `infra/scripts/deploy_web.py` or `cd infra && uv run cdk deploy ParkingLotWebStack` after building.

## Verify live MQTT

Run the IoT simulator from `parking_lot/` and watch spot tiles update in the browser within about a second. The connection pill should show **MQTT: connected**.

Click a spot to send a manual override; the tile should gain a **manual** badge and the sparkline dashed series should pick up the event.
