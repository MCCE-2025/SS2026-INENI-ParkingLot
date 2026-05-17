import type { Summary } from "../types";

interface Props {
  summary: Summary;
  lastUpdated: string;
}

export function SummaryTiles({ summary, lastUpdated }: Props) {
  return (
    <section className="summary" aria-label="Occupancy summary">
      <div className="summary__tile summary__tile--free">
        <span className="summary__value">{summary.free}</span>
        <span className="summary__label">Free</span>
      </div>
      <div className="summary__tile summary__tile--occupied">
        <span className="summary__value">{summary.occupied}</span>
        <span className="summary__label">Occupied</span>
      </div>
      <div className="summary__tile">
        <span className="summary__value">{summary.total}</span>
        <span className="summary__label">Total</span>
      </div>
      {lastUpdated ? (
        <p className="summary__updated">Last update: {lastUpdated}</p>
      ) : null}
    </section>
  );
}
