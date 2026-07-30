import { CheckCircle2, CircleX, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type AppJob } from "../../api";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import "./package-center.css";

const TERMINAL_STATUSES = new Set<AppJob["status"]>(["completed", "failed", "cancelled"]);

export function PackageJobDialog({ initialJob, jobId, moduleName, t, onClose }: { initialJob?: AppJob; jobId?: string; moduleName?: string; t: Translate; onClose: () => void }) {
  const [job, setJob] = useState<AppJob | null>(initialJob || null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const log = useRef<HTMLPreElement>(null);
  const streamRevision = useRef(0);
  const pollSequence = useRef(0);
  const latestAppliedPoll = useRef(0);
  const trackedId = jobId || initialJob?.id || "";
  const jobStatus = job?.status;

  useEffect(() => {
    if (initialJob) {
      setJob(initialJob);
      setError("");
    }
  }, [initialJob]);
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    setError("");
    setJob((current) => current?.id === jobId ? current : null);
    void api.appJob(jobId).then((next) => {
      if (active) setJob(next);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : t("error.generic"));
    });
    return () => { active = false; };
  }, [jobId, t]);
  useEffect(() => {
    if (!trackedId || !jobStatus || typeof EventSource === "undefined" || TERMINAL_STATUSES.has(jobStatus)) return;
    const source = new EventSource(`/api/apps/jobs/${encodeURIComponent(trackedId)}/events`, { withCredentials: true });
    source.onopen = () => setConnected(true);
    source.onmessage = (event) => {
      try {
        const next = JSON.parse(event.data) as AppJob;
        streamRevision.current += 1;
        setJob(next);
        if (TERMINAL_STATUSES.has(next.status)) source.close();
      } catch {
        setConnected(false);
      }
    };
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [jobStatus, trackedId]);
  useEffect(() => {
    if (!trackedId || !jobStatus || TERMINAL_STATUSES.has(jobStatus)) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      const sequence = ++pollSequence.current;
      const revisionAtStart = streamRevision.current;
      void api.appJob(trackedId).then((next) => {
        if (!active || sequence < latestAppliedPoll.current || revisionAtStart !== streamRevision.current) return;
        latestAppliedPoll.current = sequence;
        setJob(next);
      }).catch(() => { if (active) setConnected(false); }).finally(() => { polling = false; });
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [jobStatus, trackedId]);

  const lastLogId = job?.log_tail[job.log_tail.length - 1]?.id;
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [lastLogId]);

  if (!job) return <Modal wide title={moduleName || t("package.liveJobTitle").replace("{name}", "")} closeLabel={t("action.close")} onClose={onClose}>{error ? <div className="error-state" role="alert">{error}</div> : <div className="loading-state">{t("status.loading")}</div>}</Modal>;
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
