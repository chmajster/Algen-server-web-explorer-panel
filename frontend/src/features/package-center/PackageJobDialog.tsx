import { CheckCircle2, CircleX, ClipboardCopy, Download, LoaderCircle, Pause, Play } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, type AppJob } from "../../api";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { requestOperationWindow } from "./operationWindow";
import "./package-center.css";
import "./operation-progress-window.css";

const TERMINAL_STATUSES = new Set<AppJob["status"]>([
  "completed",
  "failed",
  "cancelled",
]);

function safeLogTail(value: unknown): AppJob["log_tail"] {
  return Array.isArray(value) ? value as AppJob["log_tail"] : [];
}

function logTimestamp(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "--:--:--";
  return new Date(value * 1000).toLocaleTimeString([], { hour12: false });
}

function OperationWindowFrame({
  title,
  closeLabel,
  footer,
  onClose,
  children,
  native = false,
}: {
  title: string;
  closeLabel: string;
  footer?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  native?: boolean;
}) {
  if (native) return <section className="operation-progress-native" aria-label={title}><div className="operation-progress-window-body">{children}</div>{footer && <footer>{footer}</footer>}</section>;
  return <Modal title={title} closeLabel={closeLabel} className="operation-progress-dialog" wide onClose={onClose} footer={footer}><div className="operation-progress-window-body">{children}</div></Modal>;
}

export function PackageJobDialog({
  initialJob,
  jobId,
  moduleName,
  t,
  onClose,
}: {
  initialJob?: AppJob;
  jobId?: string;
  moduleName?: string;
  t: Translate;
  onClose: () => void;
}) {
  const [delegated, setDelegated] = useState(false);
  const trackedId = jobId || initialJob?.id || "";
  const moduleId = initialJob?.module_id || "";

  useLayoutEffect(() => {
    if (!trackedId) return;
    if (requestOperationWindow({ id: trackedId, module_id: moduleId }, moduleName)) {
      setDelegated(true);
      onClose();
    }
  }, [moduleId, moduleName, onClose, trackedId]);

  if (delegated) return null;
  return <PackageJobWindow initialJob={initialJob} jobId={jobId} moduleName={moduleName} t={t} onClose={onClose} />;
}

export function PackageJobWindow({
  initialJob,
  jobId,
  moduleName,
  t,
  onClose,
  native = false,
}: {
  initialJob?: AppJob;
  jobId?: string;
  moduleName?: string;
  t: Translate;
  onClose: () => void;
  native?: boolean;
}) {
  const [job, setJob] = useState<AppJob | null>(initialJob || null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [followLogs, setFollowLogs] = useState(true);
  const [copied, setCopied] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const copyResetTimer = useRef<number>();
  const streamRevision = useRef(0);
  const pollSequence = useRef(0);
  const latestAppliedPoll = useRef(0);
  const trackedId = jobId || initialJob?.id || "";
  const jobStatus = job?.status;
  const announcedTerminal = useRef("");

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
    void api.appJob(jobId)
      .then((next) => {
        if (active) setJob(next);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(
            reason instanceof Error
              ? reason.message
              : t("error.generic"),
          );
        }
      });
    return () => {
      active = false;
    };
  }, [jobId, t]);

  useEffect(() => {
    if (
      !trackedId ||
      !jobStatus ||
      typeof EventSource === "undefined" ||
      TERMINAL_STATUSES.has(jobStatus)
    ) {
      return;
    }

    const source = new EventSource(
      `/api/apps/jobs/${encodeURIComponent(trackedId)}/events`,
      { withCredentials: true },
    );

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
    if (
      !trackedId ||
      !jobStatus ||
      TERMINAL_STATUSES.has(jobStatus)
    ) {
      return;
    }

    let active = true;
    let polling = false;

    const timer = window.setInterval(() => {
      if (polling) return;

      polling = true;
      const sequence = ++pollSequence.current;
      const revisionAtStart = streamRevision.current;

      void api.appJob(trackedId)
        .then((next) => {
          if (
            !active ||
            sequence < latestAppliedPoll.current ||
            revisionAtStart !== streamRevision.current
          ) {
            return;
          }

          latestAppliedPoll.current = sequence;
          setJob(next);
        })
        .catch(() => {
          if (active) setConnected(false);
        })
        .finally(() => {
          polling = false;
        });
    }, 2500);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [jobStatus, trackedId]);

  const logTail = safeLogTail(job?.log_tail);
  const lastLogId = logTail[logTail.length - 1]?.id;

  useEffect(() => {
    if (followLogs && log.current) {
      log.current.scrollTop = log.current.scrollHeight;
    }
  }, [followLogs, lastLogId]);

  useEffect(() => () => window.clearTimeout(copyResetTimer.current), []);

  useEffect(() => {
    if (
      !job ||
      !TERMINAL_STATUSES.has(job.status) ||
      announcedTerminal.current === `${job.id}:${job.status}`
    ) {
      return;
    }

    announcedTerminal.current = `${job.id}:${job.status}`;
    window.dispatchEvent(
      new CustomEvent("webnas:modules-changed", {
        detail: {
          moduleId: job.module_id,
          status: job.status,
          action: job.action,
        },
      }),
    );
  }, [job]);

  const fallbackName = moduleName || "";
  const fallbackTitle = t("package.liveJobTitle").replace(
    "{name}",
    fallbackName,
  );

  if (!job) {
    return (
      <OperationWindowFrame
        title={fallbackTitle}
        closeLabel={t("action.close")}
        onClose={onClose}
        native={native}
      >
        {error
          ? <div className="error-state" role="alert">{error}</div>
          : <div className="loading-state">{t("status.loading")}</div>}
      </OperationWindowFrame>
    );
  }

  const active = !TERMINAL_STATUSES.has(job.status);
  const progress = Number.isFinite(Number(job.progress))
    ? Math.max(0, Math.min(100, Number(job.progress)))
    : 0;
  const name = moduleName || job.module_id;
  const title = t("package.liveJobTitle").replace("{name}", name);
  const operation = job.operation || job.action;
  const operationLabel = operation === "container_create"
    ? t("package.containerCreateOperation")
    : operation;
  const statusIcon =
    job.status === "completed"
      ? <CheckCircle2 aria-hidden="true" />
      : job.status === "failed" || job.status === "cancelled"
        ? <CircleX aria-hidden="true" />
        : <LoaderCircle className="spin" aria-hidden="true" />;
  const lines = logTail
    .map(
      (entry) =>
        `[${logTimestamp(entry?.created_at)}] [${entry?.stream || "stdout"}] ${entry?.line || ""}`,
    )
    .join("\n");
  const currentJobId = job.id;

  async function copyLogs() {
    if (!lines || !navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(lines);
      setCopied(true);
      window.clearTimeout(copyResetTimer.current);
      copyResetTimer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  function downloadLogs() {
    if (!lines) return;
    const url = URL.createObjectURL(new Blob([`${lines}\n`], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `webnas-job-${currentJobId}.log`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function resumeFollowing() {
    setFollowLogs(true);
    window.requestAnimationFrame(() => {
      if (log.current) log.current.scrollTop = log.current.scrollHeight;
    });
  }

  return (
    <OperationWindowFrame
      title={title}
      closeLabel={t("action.close")}
      onClose={onClose}
      native={native}
      footer={(
        <>
          <span className="package-live-footer-note">
            {active
              ? t("package.backgroundJobHint")
              : t("package.operationFinished")}
          </span>
          <button type="button" onClick={onClose}>
            {t("action.close")}
          </button>
        </>
      )}
    >
      <section className={`package-live-job ${job.status}`}>
        <header>
          <div
            className="package-live-status"
            role="status"
            aria-live="polite"
          >
            {statusIcon}
            <span>
              <strong>{t(`task.${job.status}`)}</strong>
              <small>{operationLabel}</small>
            </span>
          </div>
          <strong className="package-live-progress">
            {progress}%
          </strong>
        </header>

        <div
          className="progress-track"
          aria-label={`${t("package.progress")}: ${progress}%`}
        >
          <span style={{ width: `${progress}%` }} />
        </div>

        <dl className="package-live-metadata">
          <dt>{t("package.currentStep")}</dt>
          <dd>
            {job.current_step || t("package.waitingForLogs")}
          </dd>
          <dt>{t("package.operation")}</dt>
          <dd><code>{operationLabel}</code></dd>
          <dt>{t("package.jobId")}</dt>
          <dd><code title={job.id}>{job.id}</code></dd>
          <dt>{t("package.startedAt")}</dt>
          <dd>{new Date(job.created_at * 1000).toLocaleString()}</dd>
        </dl>

        {job.error && (
          <p className="package-job-error" role="alert">
            {job.error}
          </p>
        )}

        <div className="package-live-log-header">
          <div>
            <h3>{t("package.liveLog")}</h3>
            <small>{t("package.logEntries").replace("{count}", String(logTail.length))}</small>
          </div>
          <div className="package-live-log-actions">
            {active && (
              <span className={connected ? "connected" : "reconnecting"}>
                {t(connected ? "package.logConnected" : "package.logConnecting")}
              </span>
            )}
            <button type="button" disabled={!lines} onClick={() => void copyLogs()} title={t("action.copy")}>
              <ClipboardCopy aria-hidden="true" />
              {copied ? t("package.logCopied") : t("action.copy")}
            </button>
            <button type="button" disabled={!lines} onClick={downloadLogs} title={t("action.download")}>
              <Download aria-hidden="true" />
              {t("action.download")}
            </button>
            <button
              type="button"
              aria-pressed={followLogs}
              onClick={() => followLogs ? setFollowLogs(false) : resumeFollowing()}
              title={t(followLogs ? "package.pauseLogs" : "package.followLogs")}
            >
              {followLogs ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
              {t(followLogs ? "package.pauseLogs" : "package.followLogs")}
            </button>
          </div>
        </div>

        <div
          className="package-live-log"
          ref={log}
          role="log"
          aria-live="off"
          tabIndex={0}
          onScroll={(event) => {
            const element = event.currentTarget;
            setFollowLogs(element.scrollHeight - element.scrollTop - element.clientHeight < 24);
          }}
        >
          {logTail.length
            ? logTail.map((entry) => (
                <div className={`package-live-log-line ${entry.stream || "stdout"}`} key={entry.id}>
                  <time dateTime={new Date(entry.created_at * 1000).toISOString()}>{logTimestamp(entry.created_at)}</time>
                  <span>{entry.stream || "stdout"}</span>
                  <code>{entry.line || ""}</code>
                </div>
              ))
            : <div className="package-live-log-empty">{t("package.waitingForLogs")}</div>}
        </div>
      </section>
    </OperationWindowFrame>
  );
}
