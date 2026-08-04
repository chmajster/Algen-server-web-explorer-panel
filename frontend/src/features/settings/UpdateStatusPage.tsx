import { AlertTriangle, CheckCircle2, Circle, Clock3, Copy, HardDriveDownload, LoaderCircle, LogIn, MinusCircle, RefreshCw, RotateCcw, Terminal, XCircle } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { UpdateCompletionNotice, UpdateProgress } from "../../api";
import { request } from "../../core/api/transport";
import type { Translate } from "../../app/types";

function timestamp(value: number | null | undefined) {
  return value ? new Date(value * 1000).toLocaleString() : "—";
}

function duration(started: number | null | undefined, finished: number | null | undefined, t: Translate) {
  if (!started) return "—";
  const seconds = Math.max(0, Math.round((finished || Date.now() / 1000) - started));
  return t("updateStatus.durationSeconds").replace("{count}", String(seconds));
}

function StepIcon({ status }: { status: "pending" | "running" | "success" | "failed" | "skipped" }) {
  if (status === "running") return <LoaderCircle className="spin" />;
  if (status === "success") return <CheckCircle2 />;
  if (status === "failed") return <XCircle />;
  if (status === "skipped") return <MinusCircle />;
  return <Circle />;
}

export function UpdateStatusPage({
  value,
  connectionError,
  canRetry = true,
  t,
  onRetry,
  onReturn,
  onLogin,
}: {
  value: UpdateProgress;
  connectionError: boolean;
  canRetry?: boolean;
  t: Translate;
  onRetry: () => void;
  onReturn: () => void;
  onLogin: () => void;
}) {
  const active = value.state === "waiting" || value.state === "preparing" || value.state === "running";
  const failed = value.state === "failed";
  const phase = failed ? value.failed_phase || value.phase || value.state : value.phase || value.state;
  const phaseLabel = value.steps?.some((step) => step.id === phase) ? t(`updateStatus.step.${phase}`) : t(`updateStatus.phase.${phase}`);
  const percent = value.progress ?? (value.state === "completed" || failed ? 100 : 0);
  const logRef = useRef<HTMLPreElement | null>(null);
  const [showDetailedSteps, setShowDetailedSteps] = useState(false);
  const logContent = value.lines.length ? value.lines.join("\n") : t(active ? "settings.updateWaitingForLog" : "settings.updateNoLog");

  useEffect(() => {
    let live = true;
    let retryTimer: number | undefined;
    const loadPolicy = async () => {
      try {
        const policy = await request<{ detailed_steps: boolean }>("/api/system/update-detail-policy");
        if (live) setShowDetailedSteps(policy.detailed_steps === true);
      } catch {
        if (live) retryTimer = window.setTimeout(() => void loadPolicy(), 5000);
      }
    };
    void loadPolicy();
    return () => {
      live = false;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, []);

  useLayoutEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [logContent]);
  return <main className={`update-status-page ${value.state}`}>
    <section className="update-status-shell" aria-labelledby="update-status-title">
      <header className="update-status-header">
        <span className="update-status-logo">{failed ? <AlertTriangle /> : value.state === "completed" ? <CheckCircle2 /> : <HardDriveDownload />}</span>
        <div>
          <small>WebNAS</small>
          <h1 id="update-status-title">{t("updateStatus.title")}</h1>
          <p>{value.message || t(`updateStatus.message.${value.state}`)}</p>
        </div>
        <span className={`update-status-badge ${value.state}`}>{t(`updateStatus.state.${value.state}`)}</span>
      </header>

      {connectionError && <div className="update-status-reconnecting" role="status"><RefreshCw className="spin" />{t("updateStatus.reconnecting")}</div>}

      <section className="update-status-stage" aria-live="polite">
        <div><strong>{t("updateStatus.currentStage")}</strong><span>{phaseLabel}</span></div>
        <strong>{percent}%</strong>
      </section>
      <div className={`update-status-meter ${active ? "active" : ""} ${failed ? "failed" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <span style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
      </div>

      <dl className="update-status-meta">
        <div><dt>{t("updateStatus.currentVersion")}</dt><dd>{value.current_version || value.previous_version || "—"}</dd></div>
        <div><dt>{t("updateStatus.targetVersion")}</dt><dd title={value.commit_revision || undefined}>{value.target_version || value.commit_revision?.slice(0, 12) || "—"}</dd></div>
        <div><dt>{t("updateStatus.totalDuration")}</dt><dd>{duration(value.started_at || value.requested_at, value.finished_at, t)}</dd></div>
        <div><dt>{t("updateStatus.trigger")}</dt><dd>{t(`updateStatus.trigger.${value.trigger || "manual"}`)}</dd></div>
      </dl>

      {value.state === "waiting" && <section className="update-status-blockers">
        <header><Clock3 /><div><strong>{t("updateStatus.blockersTitle")}</strong><span>{t("updateStatus.blockersCount").replace("{count}", String(value.active_count || value.blockers?.length || 0))}</span></div></header>
        <div>
          {(value.blockers || []).map((item) => <article key={`${item.type}:${item.id}`}>
            <span className={`update-status-operation-dot ${item.status}`} />
            <div><strong>{item.type}</strong><small>{item.description || item.id}</small></div>
            {item.progress !== null && <span>{item.progress}%</span>}
            <em>{t(`actions.status.${item.status}`)}</em>
          </article>)}
        </div>
      </section>}

      {showDetailedSteps && !!value.steps?.length && <ol className="update-stepper" aria-label={t("updateStatus.stepsLabel")}>
        {value.steps.map((step) => <li key={step.id} className={step.status} aria-current={step.status === "running" ? "step" : undefined}>
          <span className="update-step-icon"><StepIcon status={step.status} /></span>
          <div className="update-step-copy">
            <strong>{t(`updateStatus.step.${step.id}`)}</strong>
            <span>{step.message || t(`updateStatus.stepMessage.${step.status}`)}</span>
            {step.error && <code>{step.error}</code>}
          </div>
          <dl>
            <div><dt>{t("updateStatus.startedAt")}</dt><dd>{timestamp(step.started_at)}</dd></div>
            <div><dt>{t("updateStatus.completedAt")}</dt><dd>{timestamp(step.finished_at)}</dd></div>
            <div><dt>{t("updateStatus.duration")}</dt><dd>{duration(step.started_at, step.finished_at, t)}</dd></div>
          </dl>
        </li>)}
      </ol>}

      <details className="update-status-technical" open={failed}>
        <summary><Terminal /><strong>{t("updateStatus.technicalDetails")}</strong></summary>
        <section className="update-status-log"><pre ref={logRef}>{logContent}</pre></section>
      </details>

      <footer className="update-status-footer">
        <p><AlertTriangle />{active ? t("updateStatus.doNotInterrupt") : failed ? t("updateStatus.failedHint") : t("updateStatus.completedHint")}</p>
        {failed && <div>
          {canRetry && <button type="button" onClick={onRetry}><RotateCcw />{t("action.retry")}</button>}
          <button type="button" onClick={() => void navigator.clipboard?.writeText([value.message, ...(value.steps || []).filter((step) => step.error).map((step) => `${step.id}: ${step.error}`), ...value.lines].filter(Boolean).join("\n"))}><Copy />{t("updateStatus.copyError")}</button>
          <button type="button" onClick={onLogin}><LogIn />{t("updateStatus.returnToLogin")}</button>
          <button className="button-primary" type="button" onClick={onReturn}>{t("updateStatus.returnToPanel")}</button>
        </div>}
        {value.state === "completed" && <div><button className="button-primary" type="button" onClick={onReturn}>{t("updateStatus.returnToPanel")}</button></div>}
      </footer>
    </section>
  </main>;
}

export function UpdateCompletionDialog({ notice, t, onClose }: { notice: UpdateCompletionNotice; t: Translate; onClose: () => void }) {
  return <div className="modal-backdrop update-completion-backdrop">
    <section className="modal-panel update-completion-dialog" role="dialog" aria-modal="true" aria-labelledby="update-completion-title">
      <header className="modal-header"><CheckCircle2 /><h2 id="update-completion-title">{t("updateStatus.successTitle")}</h2></header>
      <div className="modal-body">
        <p>{t("updateStatus.successMessage")}</p>
        <dl>
          <div><dt>{t("updateStatus.previousVersion")}</dt><dd>{notice.previous_version || "—"}</dd></div>
          <div><dt>{t("updateStatus.currentVersion")}</dt><dd>{notice.current_version || "—"}</dd></div>
          <div><dt>{t("updateStatus.commitRevision")}</dt><dd><code title={notice.commit_revision || undefined}>{notice.commit_revision?.slice(0, 12) || "—"}</code></dd></div>
          <div><dt>{t("updateStatus.commitDate")}</dt><dd>{timestamp(notice.commit_date)}</dd></div>
          <div><dt>{t("updateStatus.completedAt")}</dt><dd>{timestamp(notice.finished_at)}</dd></div>
        </dl>
      </div>
      <footer className="modal-footer"><button className="button-primary" type="button" onClick={onClose}>{t("action.close")}</button></footer>
    </section>
  </div>;
}
