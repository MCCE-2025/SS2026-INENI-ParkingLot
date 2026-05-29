/** Parse event time to milliseconds (prefer ``epoch`` µs when present). */
export function eventTimeMs(item: { ts: string; epoch?: number }): number {
  if (item.epoch != null && !Number.isNaN(item.epoch)) {
    return Math.floor(item.epoch / 1000);
  }
  return Date.parse(item.ts);
}
