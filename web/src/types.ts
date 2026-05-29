export type EventSource = "device" | "web" | "truth";

export interface AppConfig {
  region: string;
  iotEndpoint: string;
  identityPoolId: string;
  apiUrl: string;
  lotId: string;
  thingName: string;
  shadowName: string;
}

export interface SpotState {
  occupied: boolean;
  ts: string;
  source?: EventSource;
}

export interface Summary {
  free: number;
  occupied: number;
  total: number;
}

export interface OccupancyState {
  lotId: string;
  deviceId: string;
  spots: Record<string, SpotState>;
  summary: Summary;
  lastUpdated: string;
  connection: "loading" | "connected" | "reconnecting" | "shadow-only" | "error";
  error: string | null;
}

export interface StatusEvent {
  lot_id: string;
  spot_id: number;
  occupied: boolean;
  ts: string;
  /** Microseconds since Unix epoch (DynamoDB attribute; optional on live MQTT). */
  epoch?: number;
  device_id: string;
  source?: EventSource;
}

export interface SummaryEvent {
  lot_id: string;
  device_id: string;
  ts: string;
  free: number;
  occupied: number;
  total: number;
}

export interface HistoryItem {
  lot_id: string;
  spot_id: number;
  occupied: boolean;
  ts: string;
  /** Microseconds since Unix epoch when present (from DynamoDB). */
  epoch?: number;
  device_id?: string;
  source?: EventSource;
}

export interface ShadowDocument {
  state?: {
    reported?: {
      lot_id?: string;
      device_id?: string;
      spots?: Record<string, SpotState>;
      summary?: Summary;
      ts?: string;
    };
  };
}
