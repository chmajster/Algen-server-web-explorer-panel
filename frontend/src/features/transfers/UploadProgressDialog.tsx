import { RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Task } from "../../api";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { formatDate, formatSize } from "../files/utils";

const terminal = new Set(["completed", "failed", "cancelled"]);

function duration(seconds: number, empty: string) {
  if (!Number.isFinite(seconds) || seconds < 0) return empty;
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor(rounded % 3600 / 60);
  const rest = rounded % 60;
  return hours ? `${hours}h ${minutes}m ${rest}s` : minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

export function UploadProgressDialog({ tasks, t, onClose, onCancel, onRetry }: {
  tasks: Task[];
  t: Translate;
  onClose: () => void;
  onCancel: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const [now, setNow] = useState(0);
  const active = tasks.some((task) => !terminal.has(task.status));
  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  const summary = useMemo(() => {
    const total = tasks.reduce((sum, task) => sum + (task.total_bytes || 0), 0);
    const transferred = tasks.reduce((sum, task) => sum + (task.bytes_transferred || 0), 0);
    const progress = total ? transferred / total * 100 : tasks.length && tasks.every((task) => task.status === "completed") ? 100 : 0;
    const startedValues = tasks.map((task) => task.started_at || task.created_at).filter(Boolean);
    const started = startedValues.length ? Math.min(...startedValues) : 0;
    const finishedValues = tasks.map((task) => task.finished_at || 0).filter(Boolean);
    const finished = !active && finishedValues.length ? Math.max(...finishedValues) : null;
    const etaValues = tasks.filter((task) => !terminal.has(task.status)).map((task) => task.eta_seconds).filter((value): value is number => value !== null && value !== undefined);
    const speed = tasks.reduce((sum, task) => sum + (task.status === "running" ? task.speed_bps || 0 : 0), 0);
    const status = !tasks.length ? "queued"
      : tasks.some((task) => task.status === "failed") ? "failed"
      : tasks.every((task) => task.status === "completed") ? "completed"
      : tasks.every((task) => task.status === "cancelled") ? "cancelled"
      : tasks.some((task) => task.status === "running") ? "running"
      : tasks.some((task) => task.status === "paused") ? "paused" : "queued";
    return { total, transferred, progress, started, finished, eta: etaValues.length ? Math.max(...etaValues) : null, speed, status };
  }, [active, tasks]);

  const failed = tasks.filter((task) => ["failed", "cancelled"].includes(task.status));
  return <Modal title={t("upload.dialogTitle")} closeLabel={t("action.close")} onClose={onClose} footer={<>
    {active && <button type="button" className="button-danger" onClick={() => tasks.filter((task) => !terminal.has(task.status)).forEach((task) => onCancel(task.id))}><X />{t("upload.cancelAll")}</button>}
    {!active && failed.length > 0 && <button type="button" onClick={() => failed.forEach((task) => onRetry(task.id))}><RotateCcw />{t("upload.retryFailed")}</button>}
    <button type="button" className="button-primary" onClick={onClose}>{t("action.close")}</button>
  </>}>
    <section className="upload-progress-dialog" aria-live="polite">
      <header><div><strong>{t(`task.${summary.status}`)}</strong><span>{Math.round(summary.progress)}%</span></div><small>{formatSize(summary.transferred)} / {formatSize(summary.total)}</small></header>
      <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, summary.progress))}%` }} /></div>
      <dl>
        <dt>{t("transfers.started")}</dt><dd>{formatDate(summary.started)}</dd>
        <dt>{t("upload.elapsed")}</dt><dd>{duration((summary.finished || now) - summary.started, "—")}</dd>
        <dt>{t("transfers.eta")}</dt><dd>{summary.finished ? t("task.completed") : duration(summary.eta ?? -1, "—")}</dd>
        <dt>{t("upload.finished")}</dt><dd>{summary.finished ? formatDate(summary.finished) : "—"}</dd>
        <dt>{t("upload.speed")}</dt><dd>{formatSize(summary.speed)}/s</dd>
        <dt>{t("upload.destination")}</dt><dd>{tasks[0]?.destination_path || "—"}</dd>
      </dl>
      <div className="upload-file-list">{tasks.map((task) => {
        const progress = Math.round(task.progress_percent ?? task.progress ?? 0);
        return <article key={task.id} className={task.status}><div><strong>{task.current_file || task.source_paths[0]}</strong><span className={`status-badge ${task.status}`}>{t(`task.${task.status}`)}</span></div><div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div><small><span>{progress}%</span><span>{formatSize(task.bytes_transferred)} / {formatSize(task.total_bytes)}</span></small>{task.error_message && <p role="alert">{task.error_message}</p>}</article>;
      })}</div>
    </section>
  </Modal>;
}
