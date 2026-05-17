# Parking Lot Web Dashboard

React + Vite SPA for real-time occupancy. Deployed by `ParkingLotWebStack` (S3 + CloudFront + API Gateway + Cognito Identity Pool).

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

## Production build

```bash
npm run build
```

Output is in `dist/`. Redeploy with `infra/scripts/deploy_web.py` or `cd infra && uv run cdk deploy ParkingLotWebStack` after building.

## Verify live MQTT

Run the IoT simulator from `parking_lot/` and watch spot tiles update in the browser within about a second. The connection pill should show **MQTT: connected**.
