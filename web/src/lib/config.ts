import type { AppConfig } from "../types";

let cached: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (cached) {
    return cached;
  }
  const response = await fetch("/config.json");
  if (!response.ok) {
    throw new Error(
      `Failed to load /config.json (${response.status}). ` +
        "Deploy ParkingLotWebStack or copy config from stack outputs into web/public/config.json.",
    );
  }
  cached = (await response.json()) as AppConfig;
  return cached;
}
