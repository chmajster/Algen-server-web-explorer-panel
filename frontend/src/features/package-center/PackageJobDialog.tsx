import { CheckCircle2, CircleX, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AppJob } from "../../api";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import "./package-center.css";

const TERMINAL_STATUSES = new Set<AppJob["status"]>(["completed", "failed", "cancelled"]);

export function PackageJobDialog({ initialJob, moduleName, t, onClose }: { initialJob: AppJob; moduleName?: string; t: Translate; onClose: () => void }) {
  const [job, setJob] = useState(initialJob);
  const [connected, setConnected] = useState(false);
  const log = useRef<HTMLPreElement>(null);

  useEffect(() => { setJob(initialJob); }, [initialJob]);
  useEffect(() => {
    if (typeof EventSource === "undefined" || TERMINAL_STATUSES.has(initialJob.status)) return;
    const source = new EventSource(`/api/apps/jobs/${encodeURIComponent(initialJob.id)}/events`);
    source.onopen = () => setConnected(true);
    source.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as AppJob;
        setJob(next);
        if (TERMINAL_STATUSES.has(next.status)) source.close();
      } catch {
        setConnected(false);
      }
    };
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [initialJob.id, initialJob.status]);

  const lastLogId = job.log_tail[job.log_tail.length - 1]?.id;
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [lastLogId]);

  const active = !TERMINAL_STATUSES.has(job.status);
  const progress = Math.max(0, Math.min(100, job.progress));
  const name = moduleName || job.module_id;
  const statusIcon = job.status === "completed" ? <CheckCircle2 aria-hidden="true" /> : job.status === "failed" || job.status === "cancelled" ? <CircleX aria-hidden="true" /> : <LoaderCircle className="spin" aria-hidden="true" />;
  const lines = job.log_tail.map((entry) => `[${entry.stream}] ${entry.line}`).join("\n");

  return <Modal wide title={t("package.liveJobTitle").replace("{name}", name)} closeLabel={t("action.close")} onClose={onClose} footer={<><span className="package-live-footer-note">{active ? t("package.backgroundJobHint") : t("package.operationFinished")}</span><button type="button" onClick={onClose}>{t("action.close")}</button></>}>
    <section className={`package-live-job ${job.status}`}>
      <header>
        <div className="package-live-status" role="status" aria-live="polite">{statusIcon}<span><strong>{t(`task.${job.status}`)}</strong><small>{job.operation || job.action}</small></span></div>
        <strong className="package-live-progress">{progress}%</strong>
      </header>
      <div className="progress-track" aria-label={`${t("package.progress")}: ${progress}%`}><span style={{ width: `${progress}%` }} /></div>
      <dl><dt>{t("package.currentStep")}</dt><dd>{job.current_step || t("package.waitingForLogs")}</dd></dl>
      {job.error && <p className="package-job-error" role="alert">{job.error}</p>}
      <div className="package-live-log-header"><h3>{t("package.liveLog")}</h3>{active && <span className={connected ? "connected" : "reconnecting"}>{t(connected ? "package.logConnected" : "package.logConnecting")}</span>}</div>
      <pre ref={log} role="log" aria-live="off" tabIndex={0}>{lines || t("package.waitingForLogs")}</pre>
    </section>
  </Modal>;
}
