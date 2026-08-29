export type RuntimeEvent = {
  type: string;
  revision: number;
  data?: Record<string, unknown>;
};

export type RuntimeConnectionState = "connecting" | "open" | "fallback";

type EventListener = (event: RuntimeEvent) => void;
type StateListener = () => void;

const listeners = new Map<string, Set<EventListener>>();
const stateListeners = new Set<StateListener>();
let source: EventSource | null = null;
let reconnectTimer: number | null = null;
let reconnectAttempt = 0;
let state: RuntimeConnectionState = "connecting";

function hasSubscribers() {
  for (const group of listeners.values()) if (group.size) return true;
  return false;
}

function setState(next: RuntimeConnectionState) {
  if (state === next) return;
  state = next;
  stateListeners.forEach((listener) => listener());
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
  reconnectTimer = null;
}

function scheduleReconnect() {
  if (!hasSubscribers() || reconnectTimer !== null || typeof window === "undefined") return;
  const delay = Math.min(30_000, 1_000 * 2 ** Math.min(reconnectAttempt, 5));
  reconnectAttempt += 1;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function closeSource() {
  source?.close();
  source = null;
}

function dispatch(raw: MessageEvent<string>) {
  try {
    const event = JSON.parse(raw.data) as RuntimeEvent;
    if (!event || typeof event.type !== "string" || typeof event.revision !== "number") return;
    listeners.get(event.type)?.forEach((listener) => listener(event));
    listeners.get("*")?.forEach((listener) => listener(event));
  } catch {
    // Ignore malformed frames. A subsequent valid event keeps the shared stream usable.
  }
}

function connect() {
  if (!hasSubscribers() || source || typeof EventSource === "undefined") {
    if (typeof EventSource === "undefined") setState("fallback");
    return;
  }
  setState("connecting");
  const next = new EventSource("/api/events", { withCredentials: true });
  source = next;
  next.onopen = () => {
    if (source !== next) return;
    reconnectAttempt = 0;
    clearReconnectTimer();
    setState("open");
  };
  next.onmessage = dispatch;
  next.onerror = () => {
    if (source !== next) return;
    closeSource();
    setState("fallback");
    scheduleReconnect();
  };
}

function stopIfIdle() {
  if (hasSubscribers()) return;
  clearReconnectTimer();
  closeSource();
  reconnectAttempt = 0;
  setState("connecting");
}

export function subscribeRuntimeEvent(type: string, listener: EventListener) {
  const group = listeners.get(type) ?? new Set<EventListener>();
  group.add(listener);
  listeners.set(type, group);
  connect();
  return () => {
    group.delete(listener);
    if (!group.size) listeners.delete(type);
    stopIfIdle();
  };
}

export function subscribeRuntimeConnection(listener: StateListener) {
  stateListeners.add(listener);
  return () => { stateListeners.delete(listener); };
}

export function runtimeConnectionState() {
  return state;
}

export function resetRuntimeEventsForTests() {
  listeners.clear();
  stateListeners.clear();
  clearReconnectTimer();
  closeSource();
  reconnectAttempt = 0;
  state = "connecting";
}
