/**
 * Presign WSS URL for AWS IoT Core MQTT-over-WebSocket (SigV4).
 * Uses the official AWS SDK signer (same as CLI / boto3).
 * @see https://docs.aws.amazon.com/iot/latest/developerguide/mqtt.html
 */
import { Sha256 } from "@aws-crypto/sha256-js";
import { formatUrl } from "@aws-sdk/util-format-url";
import { SignatureV4 } from "@aws-sdk/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";
import type { AwsCredentials } from "./cognito";

export async function presignIotWebSocketUrl(
  endpoint: string,
  region: string,
  credentials: AwsCredentials,
): Promise<string> {
  const host = endpoint.replace(/^https?:\/\//, "").replace(/\/$/, "");

  const signer = new SignatureV4({
    service: "iotdevicegateway",
    region,
    credentials: {
      accessKeyId: credentials.accessKeyId,
      secretAccessKey: credentials.secretAccessKey,
      sessionToken: credentials.sessionToken,
    },
    sha256: Sha256,
  });

  const request = new HttpRequest({
    method: "GET",
    protocol: "https:",
    hostname: host,
    path: "/mqtt",
    headers: {
      host,
    },
  });

  const signed = await signer.presign(request, { expiresIn: 900 });
  return formatUrl(signed).replace(/^https:/, "wss:");
}
