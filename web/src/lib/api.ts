import type { HistoryItem, ShadowDocument } from "../types";

function apiBase(apiUrl: string): string {
  return apiUrl.replace(/\/$/, "");
}

export async function getSnapshot(apiUrl: string): Promise<ShadowDocument> {
  const response = await fetch(`${apiBase(apiUrl)}/snapshot`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Snapshot failed (${response.status}): ${text}`);
  }
  return (await response.json()) as ShadowDocument;
}

export async function getHistory(
  apiUrl: string,
  lotId: string,
  fromIso: string,
  toIso: string,
): Promise<HistoryItem[]> {
  const params = new URLSearchParams({
    lot_id: lotId,
    from: fromIso,
    to: toIso,
  });
  const response = await fetch(`${apiBase(apiUrl)}/history?${params}`);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`History failed (${response.status}): ${text}`);
  }
  const body = (await response.json()) as { items: HistoryItem[] };
  return body.items ?? [];
}
