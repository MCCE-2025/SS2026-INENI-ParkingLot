import { useEffect, useMemo, useState } from "react";
import type { LogDirection, LogKind, MqttLogEntry } from "../lib/mqttLog";
import { formatPayload } from "../lib/mqttLog";

interface Props {
  entries: MqttLogEntry[];
  mqttConnected: boolean;
  mqttManuallyDisconnected: boolean;
  onClear: () => void;
  onDisconnect: () => void;
  onReconnect: () => void;
}

const KIND_LABELS: Record<LogKind, string> = {
  status: "status",
  summary: "summary",
  control: "control",
  system: "system",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

export function MqttConsole({
  entries,
  mqttConnected,
  mqttManuallyDisconnected,
  onClear,
  onDisconnect,
  onReconnect,
}: Props) {
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<MqttLogEntry[]>([]);
  const [directionFilter, setDirectionFilter] = useState<LogDirection | "all">(
    "all",
  );
  const [kindFilter, setKindFilter] = useState<LogKind | "all">("all");

  useEffect(() => {
    if (!paused) {
      setFrozen(entries);
    }
  }, [entries, paused]);

  const displayed = paused ? frozen : entries;

  const filtered = useMemo(() => {
    return displayed.filter((entry) => {
      if (directionFilter !== "all" && entry.direction !== directionFilter) {
        return false;
      }
      if (kindFilter !== "all" && entry.kind !== kindFilter) {
        return false;
      }
      return true;
    });
  }, [displayed, directionFilter, kindFilter]);

  const togglePause = () => {
    if (!paused) {
      setFrozen(entries);
    }
    setPaused((value) => !value);
  };

  return (
    <section className="mqtt-console" aria-label="MQTT message log">
      <div className="mqtt-console__header">
        <div>
          <h2 className="mqtt-console__title">MQTT debug</h2>
          <p className="mqtt-console__meta">
            {entries.length} message{entries.length === 1 ? "" : "s"}
            {paused ? " · paused" : ""}
          </p>
        </div>
        <div className="mqtt-console__toolbar">
          <button
            type="button"
            className="mqtt-console__btn"
            onClick={togglePause}
          >
            {paused ? "Resume" : "Pause"}
          </button>
          <button type="button" className="mqtt-console__btn" onClick={onClear}>
            Clear
          </button>
          {mqttManuallyDisconnected || !mqttConnected ? (
            <button
              type="button"
              className="mqtt-console__btn mqtt-console__btn--primary"
              onClick={onReconnect}
            >
              Reconnect MQTT
            </button>
          ) : (
            <button
              type="button"
              className="mqtt-console__btn mqtt-console__btn--warn"
              onClick={onDisconnect}
            >
              Disconnect MQTT
            </button>
          )}
        </div>
      </div>

      <div className="mqtt-console__filters" role="group" aria-label="Filters">
        <span className="mqtt-console__filter-label">Direction</span>
        {(["all", "in", "out"] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={`mqtt-console__chip${
              directionFilter === value ? " mqtt-console__chip--active" : ""
            }`}
            onClick={() => setDirectionFilter(value)}
          >
            {value}
          </button>
        ))}
        <span className="mqtt-console__filter-label">Kind</span>
        {(["all", "status", "summary", "control", "system"] as const).map(
          (value) => (
            <button
              key={value}
              type="button"
              className={`mqtt-console__chip${
                kindFilter === value ? " mqtt-console__chip--active" : ""
              }`}
              onClick={() => setKindFilter(value)}
            >
              {value}
            </button>
          ),
        )}
      </div>

      <div className="mqtt-console__list">
        {filtered.length === 0 ? (
          <p className="mqtt-console__empty">No messages yet.</p>
        ) : (
          filtered.map((entry) => (
            <article
              key={entry.id}
              className={`mqtt-row mqtt-row--${entry.direction}${
                entry.ok ? "" : " mqtt-row--error"
              }`}
            >
              <header className="mqtt-row__header">
                <span className="mqtt-row__direction">
                  {entry.direction === "in" ? "▼ in" : "▲ out"}
                </span>
                <span className={`mqtt-badge mqtt-badge--${entry.kind}`}>
                  {KIND_LABELS[entry.kind]}
                </span>
                <span className="mqtt-row__topic">{entry.topic}</span>
                {entry.qos !== undefined ? (
                  <span className="mqtt-row__qos">QoS {entry.qos}</span>
                ) : null}
                <time className="mqtt-row__time" dateTime={entry.ts}>
                  {formatTime(entry.ts)}
                </time>
              </header>
              <details className="mqtt-row__details" open={!entry.ok}>
                <summary className="mqtt-row__summary">
                  {entry.ok ? "Payload" : "Malformed payload"}
                </summary>
                <pre className="mqtt-row__payload">{formatPayload(entry.raw)}</pre>
              </details>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
