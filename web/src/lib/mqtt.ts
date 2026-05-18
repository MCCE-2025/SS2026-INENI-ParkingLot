/**
 * Live MQTT via AWS IoT Device SDK v2 (browser WSS + Cognito SigV4).
 */
import { iot, mqtt } from "aws-iot-device-sdk-v2/dist/browser";
import type { AppConfig } from "../types";
import type { AwsCredentials } from "./cognito";

export interface MqttHandlers {
  onStatus: (payload: string) => void;
  onSummary: (payload: string) => void;
  onConnected: () => void;
  onReconnecting: () => void;
  onError: (message: string) => void;
}

let connectGeneration = 0;

function wsHost(iotEndpoint: string): string {
  return iotEndpoint.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function payloadToString(payload: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    payload instanceof ArrayBuffer
      ? new Uint8Array(payload)
      : new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength);
  return new TextDecoder().decode(bytes);
}

function assertCredentials(creds: AwsCredentials): void {
  if (!creds.accessKeyId || !creds.secretAccessKey || !creds.sessionToken) {
    throw new Error(
      "Incomplete Cognito credentials for MQTT (missing access key, secret, or session token).",
    );
  }
}

export function connectParkingMqtt(
  config: AppConfig,
  getCredentials: () => Promise<AwsCredentials>,
  handlers: MqttHandlers,
): () => void {
  const myGen = ++connectGeneration;
  let stopped = false;
  let connection: mqtt.MqttClientConnection | null = null;
  let wasConnected = false;

  const isActive = () => !stopped && myGen === connectGeneration;
  const statusTopic = `parkinglot/${config.lotId}/status`;
  const summaryTopic = `parkinglot/${config.lotId}/summary`;

  void (async () => {
    try {
      const creds = await getCredentials();
      assertCredentials(creds);
      if (!isActive()) {
        return;
      }

      const clientId = `parkinglot_web_${Math.random().toString(36).slice(2, 10)}`;
      const client = new mqtt.MqttClient();
      connection = client.new_connection(
        iot.AwsIotMqttConnectionConfigBuilder.new_builder_for_websocket()
          .with_endpoint(wsHost(config.iotEndpoint))
          .with_client_id(clientId)
          .with_clean_session(true)
          .with_keep_alive_seconds(30)
          .with_credentials(
            config.region,
            creds.accessKeyId,
            creds.secretAccessKey,
            creds.sessionToken,
          )
          .build(),
      );

      connection.on("interrupt", () => {
        if (!isActive() || !wasConnected) {
          return;
        }
        handlers.onReconnecting();
      });

      connection.on("resume", () => {
        if (!isActive()) {
          return;
        }
        handlers.onConnected();
      });

      connection.on("error", (err) => {
        if (!isActive()) {
          return;
        }
        const message = err.error_name || "MQTT error";
        if (wasConnected) {
          handlers.onReconnecting();
        } else {
          handlers.onError(message);
        }
      });

      await connection.connect();
      if (!isActive()) {
        return;
      }

      await connection.subscribe(
        statusTopic,
        mqtt.QoS.AtMostOnce,
        (topic, payload) => {
          if (topic === statusTopic) {
            handlers.onStatus(payloadToString(payload));
          }
        },
      );
      await connection.subscribe(
        summaryTopic,
        mqtt.QoS.AtMostOnce,
        (topic, payload) => {
          if (topic === summaryTopic) {
            handlers.onSummary(payloadToString(payload));
          }
        },
      );

      if (!isActive()) {
        return;
      }
      wasConnected = true;
      handlers.onConnected();
    } catch (err) {
      if (!isActive()) {
        return;
      }
      handlers.onError(err instanceof Error ? err.message : String(err));
    }
  })();

  return () => {
    stopped = true;
    connectGeneration += 1;
    void connection?.disconnect();
  };
}
