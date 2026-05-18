import { secondsAgo } from "../lib/state";
import type { OccupancyState } from "../types";

interface Props {
  spots: OccupancyState["spots"];
  onToggle: (spotId: number, nextOccupied: boolean) => void;
  pending?: Set<number>;
}

function formatAgo(iso: string): string {
  const sec = secondsAgo(iso);
  if (sec === null) {
    return "";
  }
  if (sec < 60) {
    return `${sec}s ago`;
  }
  return `${Math.floor(sec / 60)}m ago`;
}

export function SpotGrid({ spots, onToggle, pending }: Props) {
  const indices = Object.keys(spots)
    .map((k) => Number(k))
    .filter((n) => !Number.isNaN(n))
    .sort((a, b) => a - b);

  if (indices.length === 0) {
    return (
      <p className="spot-grid__empty">
        No spots in shadow yet. Run the detector or simulator with IoT enabled.
      </p>
    );
  }

  return (
    <section className="spot-grid" aria-label="Parking spots">
      {indices.map((id) => {
        const spot = spots[String(id)];
        const occupied = spot.occupied;
        const isManual = spot.source === "web";
        const isPending = pending?.has(id) ?? false;
        const nextOccupied = !occupied;
        const statusLabel = isPending ? "…" : occupied ? "Occupied" : "Free";
        const title = isPending
          ? "Updating…"
          : isManual
            ? occupied
              ? "Occupied (manual override) — click to mark free"
              : "Free (manual override) — click to mark occupied"
            : occupied
              ? "Occupied (device) — click to mark free"
              : "Free (device) — click to mark occupied";

        return (
          <button
            key={id}
            type="button"
            className={`spot ${occupied ? "spot--occupied" : "spot--free"}${isManual ? " spot--manual" : ""}`}
            title={title}
            disabled={isPending}
            onClick={() => onToggle(id, nextOccupied)}
          >
            {isManual ? <span className="spot__badge">manual</span> : null}
            <span className="spot__id">#{id}</span>
            <span className="spot__status">{statusLabel}</span>
            <span className="spot__ago">{formatAgo(spot.ts)}</span>
          </button>
        );
      })}
    </section>
  );
}
