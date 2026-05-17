import type { HistoryItem } from "../types";

interface Props {
  items: HistoryItem[];
  loading: boolean;
  error: string | null;
}

/** Bucket status events into 1-minute occupancy ratios (0–1). */
export function bucketOccupancy(items: HistoryItem[], bucketMinutes = 1): number[] {
  if (items.length === 0) {
    return [];
  }
  const msPerBucket = bucketMinutes * 60 * 1000;
  const parsed = items
    .map((it) => ({ t: Date.parse(it.ts), occupied: it.occupied ? 1 : 0 }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);
  if (parsed.length === 0) {
    return [];
  }
  const start = parsed[0].t;
  const end = parsed[parsed.length - 1].t;
  const bucketCount = Math.max(1, Math.ceil((end - start) / msPerBucket) + 1);
  const sums = new Array<number>(bucketCount).fill(0);
  const counts = new Array<number>(bucketCount).fill(0);
  for (const p of parsed) {
    const idx = Math.min(bucketCount - 1, Math.floor((p.t - start) / msPerBucket));
    sums[idx] += p.occupied;
    counts[idx] += 1;
  }
  return sums.map((s, i) => (counts[i] ? s / counts[i] : 0));
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) {
    return <p className="sparkline__empty">Not enough history for a chart.</p>;
  }
  const w = 320;
  const h = 48;
  const max = Math.max(...values, 0.01);
  const step = w / (values.length - 1);
  const points = values
    .map((v, i) => `${i * step},${h - (v / max) * (h - 4) - 2}`)
    .join(" ");
  return (
    <svg className="sparkline__svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Occupancy history">
      <polyline fill="none" stroke="currentColor" strokeWidth="2" points={points} />
    </svg>
  );
}

export function SparklineHistory({ items, loading, error }: Props) {
  const buckets = bucketOccupancy(items);
  return (
    <section className="sparkline" aria-label="Occupancy history">
      <h2 className="sparkline__title">Last hour</h2>
      {loading ? <p className="sparkline__empty">Loading history…</p> : null}
      {error ? <p className="sparkline__error">{error}</p> : null}
      {!loading && !error ? <Sparkline values={buckets} /> : null}
    </section>
  );
}
