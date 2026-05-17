import mqtt, { type MqttClient } from "mqtt";
import type { AppConfig } from "../types";
import type { AwsCredentials } from "./cognito";
import { presignIotWebSocketUrl } from "./sigv4";

export interface MqttHandlers {
  onStatus: (payload: string) => void;
  onSummary: (payload: string) => void;
  onConnected: () => void;
  onReconnecting: () => void;
  onError: (message: string) => void;
}

const RECONNECT_MS = 5000;

export function connectParkingMqtt(
  config: AppConfig,
  credentials: AwsCredentials,
  handlers: MqttHandlers,
): () => void {
  let client: MqttClient | null = null;
  let stopped = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const connectOnce = () => {
    if (stopped) {
      return;
    }
    try {
      const url = presignIotWebSocketUrl(
        config.iotEndpoint,
        config.region,
        credentials,
      );
      client = mqtt.connect(url, {
        protocol: "wss",
        reconnectPeriod: 0,
        connectTimeout: 15000,
        clientId: `parkinglot_web_${Math.random().toString(36).slice(2, 10)}`,
      });

      client.on("connect", () => {
        handlers.onConnected();
        const statusTopic = `parkinglot/${config.lotId}/status`;
        const summaryTopic = `parkinglot/${config.lotId}/summary`;
        client?.subscribe([statusTopic, summaryTopic], { qos: 1 }, (err) => {
          if (err) {
            handlers.onError(`Subscribe failed: ${err.message}`);
          }
        });
      });

      client.on("message", (topic, payload) => {
        const text = payload.toString();
        if (topic.endsWith("/status")) {
          handlers.onStatus(text);
        } else if (topic.endsWith("/summary")) {
          handlers.onSummary(text);
        }
      });

      client.on("error", (err) => {
        handlers.onError(err.message);
      });

      client.on("close", () => {
        if (stopped) {
          return;
        }
        handlers.onReconnecting();
        retryTimer = setTimeout(connectOnce, RECONNECT_MS);
      });
    } catch (err) {
      handlers.onError(err instanceof Error ? err.message : String(err));
      if (!stopped) {
        handlers.onReconnecting();
        retryTimer = setTimeout(connectOnce, RECONNECT_MS);
      }
    }
  };

  connectOnce();

  return () => {
    stopped = true;
    if (retryTimer) {
      clearTimeout(retryTimer);
    }
    client?.end(true);
  };
}
