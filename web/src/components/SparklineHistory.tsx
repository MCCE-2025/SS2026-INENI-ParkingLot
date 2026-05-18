import type { EventSource, HistoryItem } from "../types";

interface Props {
  items: HistoryItem[];
  loading: boolean;
  error: string | null;
}

function itemSource(item: HistoryItem): EventSource {
  return item.source ?? "device";
}

/** Bucket status events into 1-minute occupancy ratios (0–1) on a fixed time window. */
export function bucketOccupancyInWindow(
  items: HistoryItem[],
  startMs: number,
  endMs: number,
  bucketMinutes = 1,
): number[] {
  const msPerBucket = bucketMinutes * 60 * 1000;
  const parsed = items
    .map((it) => ({ t: Date.parse(it.ts), occupied: it.occupied ? 1 : 0 }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);

  const bucketCount = Math.max(1, Math.ceil((endMs - startMs) / msPerBucket) + 1);
  const sums = new Array<number>(bucketCount).fill(0);
  const counts = new Array<number>(bucketCount).fill(0);

  for (const p of parsed) {
    if (p.t < startMs || p.t > endMs) {
      continue;
    }
    const idx = Math.min(bucketCount - 1, Math.floor((p.t - startMs) / msPerBucket));
    sums[idx] += p.occupied;
    counts[idx] += 1;
  }

  return sums.map((s, i) => (counts[i] ? s / counts[i] : 0));
}

/** Bucket status events into 1-minute occupancy ratios (0–1). */
export function bucketOccupancy(items: HistoryItem[], bucketMinutes = 1): number[] {
  if (items.length === 0) {
    return [];
  }
  const parsed = items
    .map((it) => Date.parse(it.ts))
    .filter((t) => !Number.isNaN(t))
    .sort((a, b) => a - b);
  if (parsed.length === 0) {
    return [];
  }
  return bucketOccupancyInWindow(items, parsed[0], parsed[parsed.length - 1], bucketMinutes);
}

function bucketBySource(
  items: HistoryItem[],
  source: EventSource,
  startMs: number,
  endMs: number,
  bucketMinutes = 1,
): number[] {
  const filtered = items.filter((it) => itemSource(it) === source);
  return bucketOccupancyInWindow(filtered, startMs, endMs, bucketMinutes);
}

function historyTimeBounds(items: HistoryItem[]): { start: number; end: number } | null {
  const times = items
    .map((it) => Date.parse(it.ts))
    .filter((t) => !Number.isNaN(t))
    .sort((a, b) => a - b);
  if (times.length === 0) {
    return null;
  }
  return { start: times[0], end: times[times.length - 1] };
}

function polylinePoints(values: number[], w: number, h: number, max: number): string {
  if (values.length < 2) {
    return "";
  }
  const step = w / (values.length - 1);
  return values
    .map((v, i) => `${i * step},${h - (v / max) * (h - 4) - 2}`)
    .join(" ");
}

function Legend() {
  return (
    <div className="sparkline__legend" aria-hidden="true">
      <span className="sparkline__legend-item">
        <span className="sparkline__legend-swatch sparkline__legend-swatch--device" />
        device
      </span>
      <span className="sparkline__legend-item">
        <span className="sparkline__legend-swatch sparkline__legend-swatch--web" />
        manual
      </span>
    </div>
  );
}

function SparklineDual({
  deviceValues,
  webValues,
}: {
  deviceValues: number[];
  webValues: number[];
}) {
  const len = Math.max(deviceValues.length, webValues.length);
  if (len < 2) {
    return <p className="sparkline__empty">Not enough history for a chart.</p>;
  }

  const pad = (arr: number[], target: number): number[] => {
    if (arr.length >= target) {
      return arr;
    }
    return [...arr, ...new Array(target - arr.length).fill(0)];
  };

  const device = pad(deviceValues, len);
  const web = pad(webValues, len);
  const max = Math.max(...device, ...web, 0.01);
  const w = 320;
  const h = 48;

  return (
    <>
      <Legend />
      <svg
        className="sparkline__svg"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label="Occupancy history by source"
      >
        <polyline
          className="sparkline__line sparkline__line--device"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          points={polylinePoints(device, w, h, max)}
        />
        <polyline
          className="sparkline__line sparkline__line--web"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeDasharray="4 3"
          points={polylinePoints(web, w, h, max)}
        />
      </svg>
    </>
  );
}

export function SparklineHistory({ items, loading, error }: Props) {
  const bounds = historyTimeBounds(items);
  const deviceBuckets =
    bounds === null ? [] : bucketBySource(items, "device", bounds.start, bounds.end);
  const webBuckets =
    bounds === null ? [] : bucketBySource(items, "web", bounds.start, bounds.end);

  return (
    <section className="sparkline" aria-label="Occupancy history">
      <h2 className="sparkline__title">Last 15 minutes</h2>
      {loading ? <p className="sparkline__empty">Loading history…</p> : null}
      {error ? <p className="sparkline__error">{error}</p> : null}
      {!loading && !error ? (
        <SparklineDual deviceValues={deviceBuckets} webValues={webBuckets} />
      ) : null}
    </section>
  );
}
