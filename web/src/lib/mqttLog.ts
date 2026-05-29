export type LogDirection = "in" | "out";
export type LogKind = "status" | "summary" | "control" | "system";

export interface MqttLogEntry {
  id: number;
  direction: LogDirection;
  kind: LogKind;
  topic: string;
  qos?: number;
  ts: string;
  raw: string;
  ok: boolean;
}

export const MQTT_LOG_LIMIT = 200;

let seq = 0;

export function nextLogId(): number {
  seq += 1;
  return seq;
}

export function appendLog(
  entries: MqttLogEntry[],
  entry: MqttLogEntry,
): MqttLogEntry[] {
  const next = [entry, ...entries];
  return next.length > MQTT_LOG_LIMIT ? next.slice(0, MQTT_LOG_LIMIT) : next;
}

export function kindFromTopic(topic: string, lotId: string): LogKind {
  if (topic === `parkinglot/${lotId}/status`) {
    return "status";
  }
  if (topic === `parkinglot/${lotId}/summary`) {
    return "summary";
  }
  return "system";
}

export function formatPayload(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
