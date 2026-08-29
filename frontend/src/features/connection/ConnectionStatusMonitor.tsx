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
import type { Translate } from "../../app/types";

export const CONNECTION_RESTORED_EVENT = "webnas:connection-restored";

type ConnectionPhase = "checking" | "online" | "switching" | "offline" | "restored";

export type ConnectionState = {
  phase: ConnectionPhase;
  elapsedSeconds: number;
  lastSuccessfulAt: number | null;
};

type HealthCheck = (signal: AbortSignal) => Promise<unknown>;

type MonitorOptions = {
  check?: HealthCheck;
  intervalMs?: number;
  timeoutMs?: number;
  failureThreshold?: number;
  plannedFailureThreshold?: number;
  restoredNoticeMs?: number;
  onRestored?: (durationSeconds: number) => void;
};

const initialState: ConnectionState = {
  phase: "checking",
  elapsedSeconds: 0,
  lastSuccessfulAt: null,
};

export function formatConnectionDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [hours, minutes, seconds % 60].map((value) => String(value).padStart(2, "0")).join(":");
}

export function useConnectionMonitor({
  check = api.health,
  intervalMs = 3000,
  timeoutMs = 2500,
  failureThreshold = 2,
  plannedFailureThreshold = 4,
  restoredNoticeMs = 5000,
  onRestored,
}: MonitorOptions = {}) {
  const [state, setState] = useState<ConnectionState>(initialState);
  const onRestoredRef = useRef(onRestored);

  useEffect(() => {
    onRestoredRef.current = onRestored;
  }, [onRestored]);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let failedChecks = 0;
    let phase: ConnectionPhase = "checking";
    let lastSuccessfulAt: number | null = null;
    let outageStartedAt: number | null = null;
    let lastCheckStartedAt = 0;
    let requestController: AbortController | null = null;
    let requestTimeout: number | null = null;
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
        result = await check(requestController.signal);
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
        const previousPhase = phase;
        const deploymentPhase = typeof result === "object" && result !== null && "deployment_phase" in result
          ? (result as { deployment_phase?: unknown }).deployment_phase
          : null;
        if (deploymentPhase === "switching" || deploymentPhase === "draining") {
          if (phase !== "switching") outageStartedAt = checkedAt;
          phase = "switching";
          lastSuccessfulAt = checkedAt;
          clearElapsedTimer();
          clearRestoredTimer();
          setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
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
        return;
      }

      failedChecks += 1;
      const effectiveThreshold = phase === "switching" ? plannedFailureThreshold : failureThreshold;
      if (failedChecks < effectiveThreshold || phase === "offline") return;

      clearRestoredTimer();
      phase = "offline";
      outageStartedAt = checkedAt;
      setState({ phase, elapsedSeconds: 0, lastSuccessfulAt });
      startElapsedTimer();
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
  }, [check, failureThreshold, intervalMs, plannedFailureThreshold, restoredNoticeMs, timeoutMs]);

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
