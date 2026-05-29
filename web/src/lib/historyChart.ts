import type { EventSource, HistoryItem } from "../types";
import { HISTORY_WINDOW_MS } from "./history";
import { eventTimeMs } from "./timestamp";

function itemSource(item: HistoryItem): EventSource {
  return item.source ?? "device";
}

export function chartWindow(nowMs = Date.now()): { start: number; end: number } {
  return {
    start: nowMs - HISTORY_WINDOW_MS,
    end: nowMs,
  };
}

function occupiedRatio(spotState: Map<number, boolean>, totalSpots: number): number {
  if (totalSpots <= 0) {
    return 0;
  }
  let occupied = 0;
  for (const value of spotState.values()) {
    if (value) {
      occupied += 1;
    }
  }
  return occupied / totalSpots;
}

/** Replay spot-level events per source and sample occupancy ratio at 1-minute buckets. */
export function buildOccupancySeries(
  items: HistoryItem[],
  source: EventSource,
  windowStartMs: number,
  windowEndMs: number,
  totalSpots: number,
  bucketMinutes = 1,
): number[] {
  const msPerBucket = bucketMinutes * 60 * 1000;
  const bucketCount = Math.max(
    1,
    Math.round((windowEndMs - windowStartMs) / msPerBucket),
  );

  const events = items
    .filter((it) => itemSource(it) === source)
    .map((it) => ({ t: eventTimeMs(it), spotId: it.spot_id, occupied: it.occupied }))
    .filter((e) => !Number.isNaN(e.t))
    .sort((a, b) => a.t - b.t);

  const spotState = new Map<number, boolean>();
  let eventIdx = 0;

  while (eventIdx < events.length && events[eventIdx].t < windowStartMs) {
    const e = events[eventIdx];
    spotState.set(e.spotId, e.occupied);
    eventIdx += 1;
  }

  const ratios: number[] = [];
  for (let i = 0; i < bucketCount; i += 1) {
    const bucketEnd = Math.min(windowStartMs + (i + 1) * msPerBucket, windowEndMs);
    while (eventIdx < events.length && events[eventIdx].t < bucketEnd) {
      const e = events[eventIdx];
      spotState.set(e.spotId, e.occupied);
      eventIdx += 1;
    }
    ratios.push(occupiedRatio(spotState, totalSpots));
  }

  return ratios;
}
