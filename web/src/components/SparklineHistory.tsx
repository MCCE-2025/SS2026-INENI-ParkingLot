import { useEffect, useState } from "react";
import { buildOccupancySeries, chartWindow } from "../lib/historyChart";
import type { HistoryItem } from "../types";

interface Props {
  items: HistoryItem[];
  totalSpots: number;
  loading: boolean;
  error: string | null;
}

const SVG_WIDTH = 640;
const SVG_HEIGHT = 200;
const MARGIN_LEFT = 40;
const MARGIN_RIGHT = 12;
const MARGIN_TOP = 12;
const MARGIN_BOTTOM = 28;

const CHART_WIDTH = SVG_WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
const CHART_HEIGHT = SVG_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM;
const CHART_LEFT = MARGIN_LEFT;
const CHART_TOP = MARGIN_TOP;
const CHART_BOTTOM = MARGIN_TOP + CHART_HEIGHT;

const Y_TICKS = [0, 0.5, 1];
const X_TICK_MINUTES = [0, 5, 10, 15];

function formatPercent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

function formatXLabel(minutesAgo: number): string {
  if (minutesAgo === 0) {
    return "now";
  }
  return `-${minutesAgo}m`;
}

function polylinePoints(
  values: number[],
  chartLeft: number,
  chartTop: number,
  chartWidth: number,
  chartHeight: number,
): string {
  if (values.length === 0) {
    return "";
  }
  const step = values.length > 1 ? chartWidth / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = chartLeft + i * step;
      const y = chartTop + chartHeight - v * chartHeight;
      return `${x},${y}`;
    })
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

function OccupancyChart({
  deviceValues,
  webValues,
}: {
  deviceValues: number[];
  webValues: number[];
}) {
  return (
    <>
      <Legend />
      <svg
        className="sparkline__svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        role="img"
        aria-label="Occupancy history by source"
      >
        {Y_TICKS.map((tick) => {
          const y = CHART_TOP + CHART_HEIGHT - tick * CHART_HEIGHT;
          return (
            <g key={tick}>
              <line
                className="sparkline__grid"
                x1={CHART_LEFT}
                y1={y}
                x2={CHART_LEFT + CHART_WIDTH}
                y2={y}
              />
              <text
                className="sparkline__axis-label"
                x={CHART_LEFT - 6}
                y={y + 4}
                textAnchor="end"
              >
                {formatPercent(tick)}
              </text>
            </g>
          );
        })}

        <line
          className="sparkline__axis"
          x1={CHART_LEFT}
          y1={CHART_BOTTOM}
          x2={CHART_LEFT + CHART_WIDTH}
          y2={CHART_BOTTOM}
        />
        <line
          className="sparkline__axis"
          x1={CHART_LEFT}
          y1={CHART_TOP}
          x2={CHART_LEFT}
          y2={CHART_BOTTOM}
        />

        {X_TICK_MINUTES.map((minutes) => {
          const x = CHART_LEFT + (minutes / 15) * CHART_WIDTH;
          return (
            <g key={minutes}>
              <line
                className="sparkline__tick"
                x1={x}
                y1={CHART_BOTTOM}
                x2={x}
                y2={CHART_BOTTOM + 4}
              />
              <text
                className="sparkline__axis-label"
                x={x}
                y={CHART_BOTTOM + 18}
                textAnchor="middle"
              >
                {formatXLabel(15 - minutes)}
              </text>
            </g>
          );
        })}

        <polyline
          className="sparkline__line sparkline__line--device"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          points={polylinePoints(
            deviceValues,
            CHART_LEFT,
            CHART_TOP,
            CHART_WIDTH,
            CHART_HEIGHT,
          )}
        />
        <polyline
          className="sparkline__line sparkline__line--web"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeDasharray="4 3"
          points={polylinePoints(
            webValues,
            CHART_LEFT,
            CHART_TOP,
            CHART_WIDTH,
            CHART_HEIGHT,
          )}
        />
      </svg>
    </>
  );
}

export function SparklineHistory({ items, totalSpots, loading, error }: Props) {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const { start, end } = chartWindow(nowMs);
  const deviceValues = buildOccupancySeries(items, "device", start, end, totalSpots);
  const webValues = buildOccupancySeries(items, "web", start, end, totalSpots);

  return (
    <section className="sparkline" aria-label="Occupancy history">
      <h2 className="sparkline__title">Last 15 minutes</h2>
      {loading ? <p className="sparkline__empty">Loading history…</p> : null}
      {error ? <p className="sparkline__error">{error}</p> : null}
      {!loading && !error && totalSpots === 0 ? (
        <p className="sparkline__empty">Waiting for occupancy data…</p>
      ) : null}
      {!loading && !error && totalSpots > 0 ? (
        <OccupancyChart deviceValues={deviceValues} webValues={webValues} />
      ) : null}
    </section>
  );
}
