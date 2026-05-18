import type {
  OccupancyState,
  ShadowDocument,
  StatusEvent,
  Summary,
  SummaryEvent,
} from "../types";

function emptySummary(): Summary {
  return { free: 0, occupied: 0, total: 0 };
}

function computeSummary(spots: OccupancyState["spots"]): Summary {
  const keys = Object.keys(spots);
  const occupied = keys.filter((k) => spots[k].occupied).length;
  const total = keys.length;
  return { free: total - occupied, occupied, total };
}

export function initialState(lotId: string): OccupancyState {
  return {
    lotId,
    deviceId: "",
    spots: {},
    summary: emptySummary(),
    lastUpdated: "",
    connection: "loading",
    error: null,
  };
}

export function applySnapshot(
  state: OccupancyState,
  doc: ShadowDocument,
): OccupancyState {
  const reported = doc.state?.reported;
  if (!reported) {
    return {
      ...state,
      error:
        state.connection === "connected"
          ? null
          : "Shadow has no reported state yet.",
    };
  }
  const spots = reported.spots ?? {};
  const summary = reported.summary ?? computeSummary(spots);
  return {
    ...state,
    lotId: reported.lot_id ?? state.lotId,
    deviceId: reported.device_id ?? state.deviceId,
    spots: { ...spots },
    summary,
    lastUpdated: reported.ts ?? new Date().toISOString(),
    error: null,
  };
}

export function applyStatus(
  state: OccupancyState,
  event: StatusEvent,
): OccupancyState {
  if (event.lot_id !== state.lotId) {
    return state;
  }
  const key = String(event.spot_id);
  const spots = {
    ...state.spots,
    [key]: {
      occupied: event.occupied,
      ts: event.ts,
      source: event.source ?? "device",
    },
  };
  return {
    ...state,
    deviceId: event.device_id || state.deviceId,
    spots,
    summary: computeSummary(spots),
    lastUpdated: event.ts,
    connection: "connected",
    error: null,
  };
}

export function applySummary(
  state: OccupancyState,
  event: SummaryEvent,
): OccupancyState {
  if (event.lot_id !== state.lotId) {
    return state;
  }
  return {
    ...state,
    deviceId: event.device_id || state.deviceId,
    summary: {
      free: event.free,
      occupied: event.occupied,
      total: event.total,
    },
    lastUpdated: event.ts,
    connection: "connected",
    error: null,
  };
}

export function setConnection(
  state: OccupancyState,
  connection: OccupancyState["connection"],
  error: string | null = null,
): OccupancyState {
  return { ...state, connection, error };
}

export function secondsAgo(iso: string): number | null {
  if (!iso) {
    return null;
  }
  const then = Date.parse(iso);
  if (Number.isNaN(then)) {
    return null;
  }
  return Math.max(0, Math.floor((Date.now() - then) / 1000));
}
