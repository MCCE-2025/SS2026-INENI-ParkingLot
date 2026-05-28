import { useCallback, useEffect, useReducer, useState } from "react";
import { Link } from "react-router-dom";
import { ConnectionPill } from "./components/ConnectionPill";
import { SparklineHistory } from "./components/SparklineHistory";
import { SpotGrid } from "./components/SpotGrid";
import { SummaryTiles } from "./components/SummaryTiles";
import { getHistory, getSnapshot, postControl } from "./lib/api";
import { getCognitoCredentials } from "./lib/cognito";
import { loadConfig } from "./lib/config";
import { appendHistoryItem, historyWindow } from "./lib/history";
import type { CaptureMode } from "./lib/mode";
import { connectParkingMqtt } from "./lib/mqtt";
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
  if (captureMode === "web" && source === "truth") {
    return false;
  }
  return true;
}

interface Props {
  captureMode: CaptureMode;
}

export function ParkingLotPage({ captureMode }: Props) {
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

  const handleToggle = useCallback(
    async (spotId: number, nextOccupied: boolean) => {
      if (!config) {
        return;
      }
      setControlError(null);
      setPending((s) => new Set(s).add(spotId));
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
        setControlError(err instanceof Error ? err.message : String(err));
      } finally {
        setPending((s) => {
          const next = new Set(s);
          next.delete(spotId);
          return next;
        });
      }
    },
    [config, controlSource, controlDeviceId, isTruth],
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
    let disconnectMqtt: (() => void) | undefined;

    (async () => {
      try {
        const cfg = await loadConfig();
        if (cancelled) {
          return;
        }
        setConfig(cfg);
        dispatch({
          type: "connection",
          connection: "loading",
        });

        const doc = await getSnapshot(cfg.apiUrl);
        if (cancelled) {
          return;
        }
        dispatch({ type: "snapshot", doc });

        void loadHistory(cfg);

        const getCredentials = (forceRefresh = false) =>
          getCognitoCredentials(cfg.identityPoolId, cfg.region, forceRefresh);

        disconnectMqtt = connectParkingMqtt(cfg, () => getCredentials(false), {
          onConnected: () => {
            dispatch({ type: "connection", connection: "connected" });
          },
          onReconnecting: () => {
            dispatch({ type: "connection", connection: "reconnecting" });
          },
          onError: (message) => {
            dispatch({
              type: "connection",
              connection: "shadow-only",
              error: message,
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
              /* ignore malformed */
            }
          },
          onSummary: (payload) => {
            try {
              const event = JSON.parse(payload) as SummaryEvent;
              dispatch({ type: "summary", event });
            } catch {
              /* ignore malformed */
            }
          },
        });
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
      disconnectMqtt?.();
    };
  }, [loadHistory, captureMode, isTruth]);

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
          <nav className="app__nav" aria-label="App sections">
            {isTruth ? (
              <Link to="/">Dashboard</Link>
            ) : (
              <Link to="/truth">Ground truth</Link>
            )}
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
          loading={historyLoading}
          error={historyError}
        />
      ) : null}
    </main>
  );
}
