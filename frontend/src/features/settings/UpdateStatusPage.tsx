import { AlertTriangle, CheckCircle2, Clock3, HardDriveDownload, LogIn, RefreshCw, RotateCcw, Terminal } from "lucide-react";
import type { UpdateCompletionNotice, UpdateProgress } from "../../api";
import type { Translate } from "../../app/types";

function timestamp(value: number | null | undefined) {
  return value ? new Date(value * 1000).toLocaleString() : "—";
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
  const percent = value.progress ?? (value.state === "completed" || failed ? 100 : 0);
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
        <div><strong>{t("updateStatus.currentStage")}</strong><span>{t(`updateStatus.phase.${phase}`)}</span></div>
        <strong>{percent}%</strong>
      </section>
      <div className={`update-status-meter ${active ? "active" : ""} ${failed ? "failed" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <span style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
      </div>

      <dl className="update-status-meta">
        <div><dt>{t("updateStatus.requestedAt")}</dt><dd>{timestamp(value.requested_at)}</dd></div>
        <div><dt>{t("updateStatus.startedAt")}</dt><dd>{timestamp(value.started_at)}</dd></div>
        <div><dt>{t("updateStatus.previousVersion")}</dt><dd>{value.previous_version || "—"}</dd></div>
        <div><dt>{t("updateStatus.targetVersion")}</dt><dd>{value.target_version || value.current_version || "—"}</dd></div>
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

      <section className="update-status-log">
        <header><Terminal /><strong>{t("settings.updateLiveLog")}</strong></header>
        <pre>{value.lines.length ? value.lines.join("\n") : t(active ? "settings.updateWaitingForLog" : "settings.updateNoLog")}</pre>
      </section>

      <footer className="update-status-footer">
        <p><AlertTriangle />{active ? t("updateStatus.doNotInterrupt") : failed ? t("updateStatus.failedHint") : t("updateStatus.completedHint")}</p>
        {failed && <div>
          {canRetry && <button type="button" onClick={onRetry}><RotateCcw />{t("action.retry")}</button>}
          <button type="button" onClick={onLogin}><LogIn />{t("updateStatus.returnToLogin")}</button>
          <button className="button-primary" type="button" onClick={onReturn}>{t("updateStatus.returnToPanel")}</button>
        </div>}
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
