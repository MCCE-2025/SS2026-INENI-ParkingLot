import type { HistoryItem, StatusEvent } from "../types";
import { eventTimeMs } from "./timestamp";

export const HISTORY_WINDOW_MS = 15 * 60 * 1000;

export function historyWindow(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - HISTORY_WINDOW_MS);
  return {
    from: from.toISOString(),
    to: to.toISOString(),
  };
}

function itemKey(item: Pick<HistoryItem, "spot_id" | "ts" | "epoch">): string {
  return `${item.spot_id}-${item.ts}-${item.epoch ?? ""}`;
}

/** Append a status event and keep only items within the history window. */
export function appendHistoryItem(
  items: HistoryItem[],
  event: StatusEvent | HistoryItem,
): HistoryItem[] {
  const item: HistoryItem = {
    lot_id: event.lot_id,
    spot_id: event.spot_id,
    occupied: event.occupied,
    ts: event.ts,
    epoch: event.epoch,
    device_id: event.device_id,
    source: event.source ?? "device",
  };

  const key = itemKey(item);
  if (items.some((i) => itemKey(i) === key)) {
    return items;
  }

  const cutoff = Date.now() - HISTORY_WINDOW_MS;
  return [...items, item]
    .filter((i) => {
      const t = eventTimeMs(i);
      return !Number.isNaN(t) && t >= cutoff;
    })
    .sort((a, b) => eventTimeMs(a) - eventTimeMs(b));
}
