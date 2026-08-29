import { Wifi, WifiOff } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../../api";
import { healthWebSocketUrl } from "../../core/api/transport";
import type { Translate } from "../../app/types";

export const CONNECTION_RESTORED_EVENT = "webnas:connection-restored";

type ConnectionPhase = "checking" | "online" | "switching" | "offline" | "restored";

export type ConnectionState = {
  phase: ConnectionPhase;
  elapsedSeconds: number;
  lastSuccessfulAt: number | null;
};

type HealthCheck = (signal: AbortSignal) => Promise<unknown>;
type WebSocketFactory = (url: string) => WebSocket;

type MonitorOptions = {
  check?: HealthCheck;
  intervalMs?: number;
  timeoutMs?: number;
  failureThreshold?: number;
  plannedFailureThreshold?: number;
  restoredNoticeMs?: number;
  onRestored?: (durationSeconds: number) => void;
  webSocketFactory?: WebSocketFactory;
  webSocketUrl?: string;
  pingIntervalMs?: number;
  heartbeatTimeoutMs?: number;
  reconnectDelayMs?: number;
};

const initialState: ConnectionState = {
  phase: "checking",
  elapsedSeconds: 0,
  lastSuccessfulAt: null,
};

const SOCKET_OPEN = 1;

export function formatConnectionDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [hours, minutes, seconds % 60].map((value) => String(value).padStart(2, "0")).join(":");
}

export function useConnectionMonitor({
  check,
  intervalMs = 3000,
  timeoutMs = 2500,
  failureThreshold = 2,
  plannedFailureThreshold = 4,
  restoredNoticeMs = 5000,
  onRestored,
  webSocketFactory,
  webSocketUrl,
  pingIntervalMs = 2000,
  heartbeatTimeoutMs = 6000,
  reconnectDelayMs = 1000,
}: MonitorOptions = {}) {
  const [state, setState] = useState<ConnectionState>(initialState);
  const onRestoredRef = useRef(onRestored);

  useEffect(() => {
    onRestoredRef.current = onRestored;
  }, [onRestored]);

  useEffect(() => {
    let active = true;
    let phase: ConnectionPhase = "checking";
    let lastSuccessfulAt: number | null = null;
    let outageStartedAt: number | null = null;
    let elapsedTimer: number | null = null;
    let restoredTimer: number | null = null;

    const clearElapsedTimer = () => {
      if (elapsedTimer !== null) window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    };

    const clearRestoredTimer = () => {
      if (restoredTimer !== null) window.clearTimeout(restoredTimer);
      restoredTimer = null;
    };

    const startElapsedTimer = () => {
      clearElapsedTimer();
      elapsedTimer = window.setInterval(() => {
        if (document.hidden || !active || phase !== "offline" || outageStartedAt === null) return;
        setState({
          phase: "offline",
          elapsedSeconds: Math.floor((Date.now() - outageStartedAt) / 1000),
          lastSuccessfulAt,
        });
      }, 1000);
    };

    const markOffline = (checkedAt: number) => {
      if (phase === "offline") return;
      clearRestoredTimer();
      phase = "offline";
      outageStartedAt = checkedAt;
      setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
      startElapsedTimer();
    };

    const markSuccessful = (result: unknown, checkedAt: number) => {
      const previousPhase = phase;
      const deploymentPhase = typeof result === "object" && result !== null && "deployment_phase" in result
        ? (result as { deployment_phase?: unknown }).deployment_phase
        : null;

      if (deploymentPhase === "switching" || deploymentPhase === "draining") {
        const enteringSwitch = phase !== "switching";
        if (enteringSwitch) outageStartedAt = checkedAt;
        phase = "switching";
        lastSuccessfulAt = checkedAt;
        clearElapsedTimer();
        clearRestoredTimer();
        if (enteringSwitch) setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
        return;
      }

      const durationSeconds = outageStartedAt === null
        ? 0
        : Math.floor((checkedAt - outageStartedAt) / 1000);
      lastSuccessfulAt = checkedAt;

      if (previousPhase === "offline" || previousPhase === "switching") {
        phase = "restored";
        outageStartedAt = null;
        clearElapsedTimer();
        setState({ phase, elapsedSeconds: durationSeconds, lastSuccessfulAt });
        window.dispatchEvent(new CustomEvent(CONNECTION_RESTORED_EVENT, {
          detail: { durationSeconds },
        }));
        onRestoredRef.current?.(durationSeconds);
        clearRestoredTimer();
        restoredTimer = window.setTimeout(() => {
          if (!active || phase !== "restored") return;
          phase = "online";
          setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
        }, restoredNoticeMs);
      } else if (previousPhase === "checking") {
        phase = "online";
        setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
      }
    };

    setState(initialState);

    const canUseNativeWebSocket = typeof WebSocket !== "undefined";
    const pollingCheck = check ?? (!webSocketFactory && !canUseNativeWebSocket ? api.health : undefined);

    if (pollingCheck) {
      let inFlight = false;
      let failedChecks = 0;
      let lastCheckStartedAt = 0;
      let requestController: AbortController | null = null;
      let requestTimeout: number | null = null;

      const runCheck = async () => {
        const startedAt = Date.now();
        if (!active || inFlight || startedAt - lastCheckStartedAt < 250) return;
        lastCheckStartedAt = startedAt;
        inFlight = true;
        let timedOut = false;
        requestController = new AbortController();
        requestTimeout = window.setTimeout(() => {
          timedOut = true;
          requestController?.abort();
        }, timeoutMs);

        let successful: boolean;
        let result: unknown;
        try {
          result = await pollingCheck(requestController.signal);
          successful = !timedOut;
        } catch {
          successful = false;
        } finally {
          if (requestTimeout !== null) window.clearTimeout(requestTimeout);
          requestTimeout = null;
          requestController = null;
          inFlight = false;
        }

        if (!active) return;
        const checkedAt = Date.now();

        if (successful) {
          failedChecks = 0;
          markSuccessful(result, checkedAt);
          return;
        }

        failedChecks += 1;
        const effectiveThreshold = phase === "switching" ? plannedFailureThreshold : failureThreshold;
        if (failedChecks >= effectiveThreshold) markOffline(checkedAt);
      };

      const checkWhenActive = () => {
        if (document.visibilityState === "visible") void runCheck();
      };

      void runCheck();
      const pollTimer = window.setInterval(checkWhenActive, intervalMs);
      document.addEventListener("visibilitychange", checkWhenActive);
      window.addEventListener("focus", checkWhenActive);

      return () => {
        active = false;
        window.clearInterval(pollTimer);
        if (requestTimeout !== null) window.clearTimeout(requestTimeout);
        clearElapsedTimer();
        clearRestoredTimer();
        requestController?.abort();
        document.removeEventListener("visibilitychange", checkWhenActive);
        window.removeEventListener("focus", checkWhenActive);
      };
    }

    const createWebSocket = webSocketFactory ?? ((url: string) => new WebSocket(url));
    let socket: WebSocket | null = null;
    let pingTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let failedConnections = 0;
    let lastHeartbeatAt = Date.now();

    const clearPingTimer = () => {
      if (pingTimer !== null) window.clearInterval(pingTimer);
      pingTimer = null;
    };

    const clearHeartbeatTimer = () => {
      if (heartbeatTimer !== null) window.clearTimeout(heartbeatTimer);
      heartbeatTimer = null;
    };

    const clearReconnectTimer = () => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    };

    let connect: () => void;

    const scheduleReconnect = () => {
      if (!active || reconnectTimer !== null) return;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, reconnectDelayMs);
    };

    const recordConnectionFailure = () => {
      failedConnections += 1;
      const effectiveThreshold = phase === "switching" ? plannedFailureThreshold : failureThreshold;
      if (phase === "online" || phase === "restored" || failedConnections >= effectiveThreshold) {
        markOffline(Date.now());
      }
      scheduleReconnect();
    };

    const detachSocket = (lostSocket: WebSocket) => {
      if (socket !== lostSocket) return false;
      socket = null;
      clearPingTimer();
      clearHeartbeatTimer();
      return true;
    };

    const handleSocketLoss = (lostSocket: WebSocket) => {
      if (!active || !detachSocket(lostSocket)) return;
      recordConnectionFailure();
    };

    const sendPing = (targetSocket: WebSocket) => {
      if (!active || socket !== targetSocket || targetSocket.readyState !== SOCKET_OPEN) return;
      try {
        targetSocket.send("ping");
      } catch {
        handleSocketLoss(targetSocket);
        try { targetSocket.close(); } catch { /* already disconnected */ }
      }
    };

    const armHeartbeatWatchdog = () => {
      clearHeartbeatTimer();
      const remaining = Math.max(1, heartbeatTimeoutMs - (Date.now() - lastHeartbeatAt));
      heartbeatTimer = window.setTimeout(() => {
        heartbeatTimer = null;
        if (!active || document.hidden) return;
        if (Date.now() - lastHeartbeatAt < heartbeatTimeoutMs) {
          armHeartbeatWatchdog();
          return;
        }
        const staleSocket = socket;
        if (!staleSocket) {
          recordConnectionFailure();
          return;
        }
        if (phase === "switching") {
          handleSocketLoss(staleSocket);
        } else {
          detachSocket(staleSocket);
          markOffline(Date.now());
          scheduleReconnect();
        }
        try { staleSocket.close(4000, "heartbeat timeout"); } catch { /* already disconnected */ }
      }, remaining);
    };

    connect = () => {
      if (!active || socket !== null) return;
      clearReconnectTimer();
      lastHeartbeatAt = Date.now();

      let nextSocket: WebSocket;
      try {
        nextSocket = createWebSocket(webSocketUrl ?? healthWebSocketUrl());
      } catch {
        recordConnectionFailure();
        return;
      }
      socket = nextSocket;
      armHeartbeatWatchdog();

      nextSocket.onopen = () => {
        if (!active || socket !== nextSocket) return;
        sendPing(nextSocket);
        clearPingTimer();
        pingTimer = window.setInterval(() => sendPing(nextSocket), pingIntervalMs);
      };

      nextSocket.onmessage = (event) => {
        if (!active || socket !== nextSocket) return;
        let payload: unknown;
        try {
          payload = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (typeof payload !== "object" || payload === null) return;
        const heartbeat = payload as { type?: unknown; status?: unknown };
        if (heartbeat.type !== "heartbeat" || heartbeat.status !== "ok") return;
        failedConnections = 0;
        lastHeartbeatAt = Date.now();
        markSuccessful(payload, lastHeartbeatAt);
        armHeartbeatWatchdog();
      };

      nextSocket.onclose = () => handleSocketLoss(nextSocket);
      nextSocket.onerror = () => {
        if (nextSocket.readyState !== SOCKET_OPEN) handleSocketLoss(nextSocket);
      };
    };

    const checkSocketWhenActive = () => {
      if (!active || document.visibilityState !== "visible") return;
      const currentSocket = socket;
      if (!currentSocket) {
        connect();
        return;
      }
      if (Date.now() - lastHeartbeatAt >= heartbeatTimeoutMs) {
        if (phase === "switching") handleSocketLoss(currentSocket);
        else {
          detachSocket(currentSocket);
          markOffline(Date.now());
          scheduleReconnect();
        }
        try { currentSocket.close(4000, "stale heartbeat"); } catch { /* already disconnected */ }
        return;
      }
      sendPing(currentSocket);
      armHeartbeatWatchdog();
    };

    connect();
    document.addEventListener("visibilitychange", checkSocketWhenActive);
    window.addEventListener("focus", checkSocketWhenActive);

    return () => {
      active = false;
      clearPingTimer();
      clearHeartbeatTimer();
      clearReconnectTimer();
      clearElapsedTimer();
      clearRestoredTimer();
      document.removeEventListener("visibilitychange", checkSocketWhenActive);
      window.removeEventListener("focus", checkSocketWhenActive);
      const currentSocket = socket;
      socket = null;
      if (currentSocket) {
        currentSocket.onopen = null;
        currentSocket.onmessage = null;
        currentSocket.onclose = null;
        currentSocket.onerror = null;
        try { currentSocket.close(1000, "monitor stopped"); } catch { /* already disconnected */ }
      }
    };
  }, [
    check,
    failureThreshold,
    heartbeatTimeoutMs,
    intervalMs,
    pingIntervalMs,
    plannedFailureThreshold,
    reconnectDelayMs,
    restoredNoticeMs,
    timeoutMs,
    webSocketFactory,
    webSocketUrl,
  ]);

  return state;
}

export function ConnectionStatusMonitor({
  t,
  language,
  ...options
}: MonitorOptions & { t: Translate; language: string }) {
  const state = useConnectionMonitor(options);
  if (state.phase === "checking" || state.phase === "online") return null;

  const offline = state.phase === "offline";
  const switching = state.phase === "switching";
  const lastSuccessful = state.lastSuccessfulAt === null
    ? t("connection.never")
    : new Date(state.lastSuccessfulAt).toLocaleString(language);

  return <aside
    className={`connection-status-banner ${state.phase}`}
    role={offline ? "alert" : "status"}
    aria-live={offline ? "assertive" : "polite"}
  >
    {offline ? <WifiOff aria-hidden="true" /> : <Wifi aria-hidden="true" />}
    <div className="connection-status-copy">
      <strong>{t(offline ? "connection.lost" : switching ? "connection.switching" : "connection.restored")}</strong>
      <span>{t(offline ? "connection.reconnecting" : switching ? "connection.switchingHint" : "connection.restoredHint")}</span>
    </div>
    {!switching && <dl>
      <div>
        <dt>{t(offline ? "connection.offlineDuration" : "connection.outageDuration")}</dt>
        <dd>{formatConnectionDuration(state.elapsedSeconds)}</dd>
      </div>
      <div>
        <dt>{t("connection.lastSuccessful")}</dt>
        <dd>{lastSuccessful}</dd>
      </div>
    </dl>}
  </aside>;
}

const ConnectionRefreshContext = createContext(true);

export function ConnectionRefreshScope({ active, children }: { active: boolean; children: ReactNode }) {
  return <ConnectionRefreshContext.Provider value={active}>{children}</ConnectionRefreshContext.Provider>;
}

export function useRefreshOnConnectionRestored(refresh: () => void) {
  const active = useContext(ConnectionRefreshContext);
  const refreshRef = useRef(refresh);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    const restored = () => refreshRef.current();
    window.addEventListener(CONNECTION_RESTORED_EVENT, restored);
    return () => window.removeEventListener(CONNECTION_RESTORED_EVENT, restored);
  }, [active]);
}
