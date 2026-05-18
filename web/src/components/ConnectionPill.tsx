import type { OccupancyState } from "../types";

const LABELS: Record<OccupancyState["connection"], string> = {
  loading: "Connecting MQTT…",
  connected: "MQTT: connected",
  reconnecting: "MQTT: reconnecting",
  "shadow-only": "Snapshot only (no MQTT)",
  error: "Connection error",
};

const CLASS: Record<OccupancyState["connection"], string> = {
  loading: "pill pill--loading",
  connected: "pill pill--ok",
  reconnecting: "pill pill--warn",
  "shadow-only": "pill pill--muted",
  error: "pill pill--error",
};

interface Props {
  connection: OccupancyState["connection"];
}

export function ConnectionPill({ connection }: Props) {
  return <span className={CLASS[connection]}>{LABELS[connection]}</span>;
}
