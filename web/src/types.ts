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
  device_id: string;
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
  device_id?: string;
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
