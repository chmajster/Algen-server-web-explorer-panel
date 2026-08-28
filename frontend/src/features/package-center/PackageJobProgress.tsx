import { Ban, ChevronDown, ChevronUp, RotateCcw } from "lucide-react";
import { useState } from "react";
import type { Translate } from "../../app/types";
import type { PackageJob } from "./types";

export function PackageJobProgress({ job, canCancel = true, canRetry = true, t, onCancel, onRetry }: { job: PackageJob; canCancel?: boolean; canRetry?: boolean; t: Translate; onCancel: () => void; onRetry: () => void }) {
  const [expanded, setExpanded] = useState(job.status === "failed"); const active = ["queued", "running"].includes(job.status) && job.cancellable !== false;
  return <article className={`package-job ${job.status}`}><header><div><strong>{job.module_id}</strong><span>{t(`store.${job.action}`)} · {t(`task.${job.status}`)}</span></div><time>{new Date(job.created_at * 1000).toLocaleString()}</time></header><div className="progress-track"><span style={{ width: `${job.progress}%` }} /></div><div className="package-job-meta"><span>{job.progress}%</span><strong>{job.current_step}</strong><div>{canCancel && active && <button type="button" onClick={onCancel}><Ban />{t("package.cancelJob")}</button>}{canRetry && ["failed", "cancelled"].includes(job.status) && <button type="button" onClick={onRetry}><RotateCcw />{t("action.retry")}</button>}<button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? <ChevronUp /> : <ChevronDown />}{t("package.logs")}</button></div></div>{job.error && <p className="package-job-error">{job.error}</p>}{expanded && <pre>{job.log_tail.map((entry) => `${entry.stream}: ${entry.line}`).join("\n") || t("package.noLogs")}</pre>}</article>;
}
