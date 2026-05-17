/**
 * Presign WSS URL for AWS IoT Core MQTT-over-WebSocket (SigV4).
 * @see https://docs.aws.amazon.com/iot/latest/developerguide/custom-auth.html
 * @see https://docs.aws.amazon.com/general/latest/gr/sigv4_signing.html
 */
import { Sha256 } from "@aws-crypto/sha256-js";
import type { AwsCredentials } from "./cognito";

const SERVICE = "iotdevicegateway";

function hmac(key: Uint8Array, data: string): Uint8Array {
  const hash = new Sha256(key);
  hash.update(toUtf8(data));
  return hash.digestSync();
}

function toUtf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function sha256Hex(data: string): string {
  const hash = new Sha256();
  hash.update(toUtf8(data));
  return hex(hash.digestSync());
}

function uriEncode(value: string, encodeSlash = false): string {
  return value
    .split("")
    .map((ch) => {
      if (
        (ch >= "A" && ch <= "Z") ||
        (ch >= "a" && ch <= "z") ||
        (ch >= "0" && ch <= "9") ||
        ch === "_" ||
        ch === "-" ||
        ch === "~" ||
        ch === "."
      ) {
        return ch;
      }
      if (ch === "/" && !encodeSlash) {
        return ch;
      }
      return `%${ch.charCodeAt(0).toString(16).toUpperCase().padStart(2, "0")}`;
    })
    .join("");
}

function signingKey(
  secretKey: string,
  dateStamp: string,
  region: string,
  service: string,
): Uint8Array {
  const kDate = hmac(toUtf8(`AWS4${secretKey}`), dateStamp);
  const kRegion = hmac(kDate, region);
  const kService = hmac(kRegion, service);
  return hmac(kService, "aws4_request");
}

export function presignIotWebSocketUrl(
  endpoint: string,
  region: string,
  credentials: AwsCredentials,
): string {
  const host = endpoint.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const now = new Date();
  const amzDate = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const dateStamp = amzDate.slice(0, 8);
  const credentialScope = `${dateStamp}/${region}/${SERVICE}/aws4_request`;
  const credential = `${credentials.accessKeyId}/${credentialScope}`;

  const query: Record<string, string> = {
    "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
    "X-Amz-Credential": credential,
    "X-Amz-Date": amzDate,
    "X-Amz-SignedHeaders": "host",
    "X-Amz-Security-Token": credentials.sessionToken,
  };

  const canonicalQuery = Object.keys(query)
    .sort()
    .map((k) => `${uriEncode(k)}=${uriEncode(query[k])}`)
    .join("&");

  const canonicalRequest = [
    "GET",
    "/mqtt",
    canonicalQuery,
    `host:${host}\n`,
    "host",
    "SHA256",
    sha256Hex(""),
  ].join("\n");

  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    sha256Hex(canonicalRequest),
  ].join("\n");

  const signature = hex(
    hmac(
      signingKey(credentials.secretAccessKey, dateStamp, region, SERVICE),
      stringToSign,
    ),
  );

  return `wss://${host}/mqtt?${canonicalQuery}&X-Amz-Signature=${signature}`;
}
