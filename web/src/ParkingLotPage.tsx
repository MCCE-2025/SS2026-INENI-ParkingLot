import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ConnectionPill } from "./components/ConnectionPill";
import { MqttConsole } from "./components/MqttConsole";
import { SparklineHistory } from "./components/SparklineHistory";
import { SpotGrid } from "./components/SpotGrid";
import { SummaryTiles } from "./components/SummaryTiles";
import { ThemeToggle } from "./components/ThemeToggle";
import { getHistory, getSnapshot, postControl } from "./lib/api";
import { getCognitoCredentials } from "./lib/cognito";
import { loadConfig } from "./lib/config";
import { appendHistoryItem, historyWindow } from "./lib/history";
import type { CaptureMode } from "./lib/mode";
import { connectParkingMqtt } from "./lib/mqtt";
import {
  appendLog,
  kindFromTopic,
  nextLogId,
  type MqttLogEntry,
} from "./lib/mqttLog";
import {
  applySnapshot,
  applyStatus,
  applySummary,
  initialState,
  setConnection,
} from "./lib/state";
import type {
  AppConfig,
  EventSource,
  HistoryItem,
  OccupancyState,
  StatusEvent,
  SummaryEvent,
} from "./types";

type Action =
  | { type: "snapshot"; doc: Parameters<typeof applySnapshot>[1] }
  | { type: "status"; event: StatusEvent }
  | { type: "summary"; event: SummaryEvent }
  | {
      type: "connection";
      connection: OccupancyState["connection"];
      error?: string | null;
    };

function reducer(state: OccupancyState, action: Action): OccupancyState {
  switch (action.type) {
    case "snapshot":
      return applySnapshot(state, action.doc);
    case "status":
      return applyStatus(state, action.event);
    case "summary":
      return applySummary(state, action.event);
    case "connection":
      return setConnection(state, action.connection, action.error ?? null);
    default:
      return state;
  }
}

function shouldApplyStatus(event: StatusEvent, captureMode: CaptureMode): boolean {
  const source = event.source ?? "device";
  if (captureMode === "truth") {
    return source === "truth";
  }
  return source !== "truth";
}

function systemLog(raw: string, ok = true): Omit<MqttLogEntry, "id" | "ts"> {
  return {
    direction: "in",
    kind: "system",
    topic: "—",
    raw,
    ok,
  };
}

interface Props {
  captureMode: CaptureMode;
}

export function ParkingLotPage({ captureMode }: Props) {
  const [searchParams] = useSearchParams();
  const debugMode = searchParams.get("debug") === "1";

  const isTruth = captureMode === "truth";
  const controlSource: EventSource = isTruth ? "truth" : "web";
  const controlDeviceId = isTruth ? "truth_capture" : "web_control";

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [state, dispatch] = useReducer(reducer, null, () =>
    initialState("lot_1"),
  );
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<number>>(() => new Set());
  const [controlError, setControlError] = useState<string | null>(null);
  const [mqttLog, setMqttLog] = useState<MqttLogEntry[]>([]);
  const [mqttConnectKey, setMqttConnectKey] = useState(0);
  const [mqttManuallyDisconnected, setMqttManuallyDisconnected] = useState(false);

  const disconnectMqttRef = useRef<(() => void) | null>(null);

  const pushLog = useCallback((partial: Omit<MqttLogEntry, "id" | "ts">) => {
    const entry: MqttLogEntry = {
      id: nextLogId(),
      ts: new Date().toISOString(),
      ...partial,
    };
    setMqttLog((entries) => appendLog(entries, entry));
  }, []);

  const clearLog = useCallback(() => {
    setMqttLog([]);
  }, []);

  const handleDisconnectMqtt = useCallback(() => {
    disconnectMqttRef.current?.();
    disconnectMqttRef.current = null;
    setMqttManuallyDisconnected(true);
    dispatch({ type: "connection", connection: "disconnected" });
    pushLog({
      direction: "out",
      kind: "system",
      topic: "—",
      raw: "Manual MQTT disconnect",
      ok: true,
    });
  }, [pushLog]);

  const handleReconnectMqtt = useCallback(() => {
    setMqttManuallyDisconnected(false);
    setMqttConnectKey((key) => key + 1);
    dispatch({ type: "connection", connection: "loading" });
    pushLog({
      direction: "out",
      kind: "system",
      topic: "—",
      raw: "Manual MQTT reconnect requested",
      ok: true,
    });
  }, [pushLog]);

  const handleToggle = useCallback(
    async (spotId: number, nextOccupied: boolean) => {
      if (!config) {
        return;
      }
      setControlError(null);
      setPending((s) => new Set(s).add(spotId));

      const controlBody = {
        spot_id: spotId,
        occupied: nextOccupied,
        source: controlSource,
      };
      if (debugMode) {
        pushLog({
          direction: "out",
          kind: "control",
          topic: `parkinglot/${config.lotId}/status`,
          raw: JSON.stringify(controlBody, null, 2),
          ok: true,
        });
      }

      try {
        const result = await postControl(
          config.apiUrl,
          spotId,
          nextOccupied,
          controlSource,
        );
        setHistory((items) =>
          appendHistoryItem(items, {
            lot_id: config.lotId,
            spot_id: result.spot_id,
            occupied: result.occupied,
            ts: result.ts,
            device_id: controlDeviceId,
            source: controlSource,
          }),
        );
        if (isTruth) {
          dispatch({
            type: "status",
            event: {
              lot_id: config.lotId,
              spot_id: result.spot_id,
              occupied: result.occupied,
              ts: result.ts,
              device_id: controlDeviceId,
              source: "truth",
            },
          });
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setControlError(message);
        if (debugMode) {
          pushLog({
            direction: "out",
            kind: "control",
            topic: `parkinglot/${config.lotId}/status`,
            raw: `Control failed: ${message}`,
            ok: false,
          });
        }
      } finally {
        setPending((s) => {
          const next = new Set(s);
          next.delete(spotId);
          return next;
        });
      }
    },
    [config, controlSource, controlDeviceId, isTruth, debugMode, pushLog],
  );

  const loadHistory = useCallback(
    async (cfg: AppConfig) => {
      if (isTruth) {
        return;
      }
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const { from, to } = historyWindow();
        const items = await getHistory(cfg.apiUrl, cfg.lotId, from, to);
        setHistory(items);
      } catch (err) {
        setHistoryError(err instanceof Error ? err.message : String(err));
      } finally {
        setHistoryLoading(false);
      }
    },
    [isTruth],
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const cfg = await loadConfig();
        if (cancelled) {
          return;
        }
        setConfig(cfg);
        dispatch({ type: "connection", connection: "loading" });

        const doc = await getSnapshot(cfg.apiUrl);
        if (cancelled) {
          return;
        }
        dispatch({ type: "snapshot", doc });
        void loadHistory(cfg);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setBootError(message);
        dispatch({
          type: "connection",
          connection: "error",
          error: message,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  useEffect(() => {
    if (!config || mqttManuallyDisconnected) {
      return;
    }

    let cancelled = false;
    let disconnectMqtt: (() => void) | undefined;
    const cfg = config;

    const getCredentials = (forceRefresh = false) =>
      getCognitoCredentials(cfg.identityPoolId, cfg.region, forceRefresh);

    disconnectMqtt = connectParkingMqtt(cfg, () => getCredentials(false), {
      onConnected: () => {
        if (cancelled) {
          return;
        }
        dispatch({ type: "connection", connection: "connected" });
        if (debugMode) {
          pushLog(systemLog("MQTT connected"));
        }
      },
      onReconnecting: () => {
        if (cancelled) {
          return;
        }
        dispatch({ type: "connection", connection: "reconnecting" });
        if (debugMode) {
          pushLog(systemLog("MQTT reconnecting"));
        }
      },
      onError: (message) => {
        if (cancelled) {
          return;
        }
        dispatch({
          type: "connection",
          connection: "shadow-only",
          error: message,
        });
        if (debugMode) {
          pushLog(systemLog(`MQTT error: ${message}`, false));
        }
      },
      onMessage: (topic, payload, qos) => {
        if (!debugMode) {
          return;
        }
        let ok = true;
        try {
          JSON.parse(payload);
        } catch {
          ok = false;
        }
        pushLog({
          direction: "in",
          kind: kindFromTopic(topic, cfg.lotId),
          topic,
          qos,
          raw: payload,
          ok,
        });
      },
      onStatus: (payload) => {
        try {
          const event = JSON.parse(payload) as StatusEvent;
          if (!shouldApplyStatus(event, captureMode)) {
            return;
          }
          dispatch({ type: "status", event });
          if (!isTruth) {
            setHistory((items) => appendHistoryItem(items, event));
          }
        } catch {
          /* malformed payloads logged via onMessage in debug mode */
        }
      },
      onSummary: (payload) => {
        try {
          const event = JSON.parse(payload) as SummaryEvent;
          dispatch({ type: "summary", event });
        } catch {
          /* malformed payloads logged via onMessage in debug mode */
        }
      },
    });

    disconnectMqttRef.current = disconnectMqtt;

    return () => {
      cancelled = true;
      disconnectMqtt?.();
      if (disconnectMqttRef.current === disconnectMqtt) {
        disconnectMqttRef.current = null;
      }
    };
  }, [
    config,
    mqttConnectKey,
    mqttManuallyDisconnected,
    captureMode,
    isTruth,
    debugMode,
    pushLog,
  ]);

  if (bootError && !config) {
    return (
      <main className="app app--error">
        <h1>{isTruth ? "Ground truth capture" : "Parking Lot"}</h1>
        <p className="app__error">{bootError}</p>
        <p className="app__hint">
          For local dev, copy stack outputs into <code>web/public/config.json</code>.
        </p>
      </main>
    );
  }

  const mqttConnected = state.connection === "connected";

  return (
    <main className={`app${isTruth ? " app--truth" : ""}`}>
      {isTruth ? (
        <div className="app__banner app__banner--truth" role="status">
          Ground truth capture — labels are stored with{" "}
          <code>source: truth</code> in DynamoDB and do not update the live
          shadow.
        </div>
      ) : null}

      <header className="app__header">
        <div>
          <h1>{isTruth ? "Ground truth capture" : "Parking Lot"}</h1>
          <p className="app__subtitle">
            {config?.lotId ?? state.lotId}
            {state.deviceId ? ` · ${state.deviceId}` : ""}
          </p>
        </div>
        <div className="app__header-actions">
          <ThemeToggle />
          <nav className="app__nav" aria-label="App sections">
            {isTruth ? (
              <Link to="/" className="app__nav-link">
                Dashboard
              </Link>
            ) : (
              <Link to="/truth" className="app__nav-link">
                Ground truth
              </Link>
            )}
            {!isTruth && !debugMode ? (
              <Link to="/?debug=1" className="app__nav-link">
                MQTT debug
              </Link>
            ) : null}
            {debugMode && !isTruth ? (
              <Link to="/" className="app__nav-link app__nav-link--active">
                Exit debug
              </Link>
            ) : null}
          </nav>
          <ConnectionPill connection={state.connection} />
        </div>
      </header>

      {state.error ? <p className="app__error">{state.error}</p> : null}
      {controlError ? <p className="app__error">{controlError}</p> : null}

      <SummaryTiles summary={state.summary} lastUpdated={state.lastUpdated} />
      <SpotGrid
        spots={state.spots}
        onToggle={handleToggle}
        pending={pending}
        highlightSource={isTruth ? "truth" : "web"}
      />
      {!isTruth ? (
        <SparklineHistory
          items={history}
          totalSpots={state.summary.total}
          loading={historyLoading}
          error={historyError}
        />
      ) : null}
      {debugMode && !isTruth ? (
        <MqttConsole
          entries={mqttLog}
          mqttConnected={mqttConnected}
          mqttManuallyDisconnected={mqttManuallyDisconnected}
          onClear={clearLog}
          onDisconnect={handleDisconnectMqtt}
          onReconnect={handleReconnectMqtt}
        />
      ) : null}
    </main>
  );
}
