import { ChevronDown, ChevronUp, Pause, Play, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type SettingsMe, type Task } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { formatDate, formatSize } from "../files/utils";
import type { UploadControls } from "./useUploadManager";

type TransferFilter = "all" | "active" | "completed" | "failed";

export function TransferCenter({ tasks, settings, selectedTaskId, t, toast, uploadControls, onSelectedTaskClose }: { tasks: Task[]; settings: SettingsMe; selectedTaskId?: string; t: Translate; toast: ToastFn; uploadControls: UploadControls; onSelectedTaskClose?: () => void }) {
  const filterKey = `webnas_transfer_filter_${settings.username}`;
  const [filter, setFilter] = useState<TransferFilter>(() => settings.transfer_remember_filter ? (localStorage.getItem(filterKey) as TransferFilter) || "all" : "all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [highlighted, setHighlighted] = useState("");
  const cards = useRef(new Map<string, HTMLElement>());
  const handledSelectedTask = useRef("");
  const visible = useMemo(() => tasks.filter((task) => !hidden.has(task.id) && (filter === "all" || filter === "active" && ["queued", "running", "paused"].includes(task.status) || task.status === filter)), [filter, hidden, tasks]);
  async function run(action: () => Promise<unknown>) { try { await action(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } }
  const completed = tasks.filter((task) => ["completed", "cancelled", "failed"].includes(task.status)).map((task) => task.id);
  const can = (permission: string) => settings.permissions.includes(permission);
  useEffect(() => {
    if (!selectedTaskId) { handledSelectedTask.current = ""; return; }
    if (handledSelectedTask.current === selectedTaskId || !tasks.some((task) => task.id === selectedTaskId)) return;
    handledSelectedTask.current = selectedTaskId;
    setFilter("all");
    setHidden((current) => {
      if (!current.has(selectedTaskId)) return current;
      const next = new Set(current); next.delete(selectedTaskId); return next;
    });
    setExpanded((current) => new Set(current).add(selectedTaskId));
    setHighlighted(selectedTaskId);
    const frame = window.requestAnimationFrame(() => cards.current.get(selectedTaskId)?.scrollIntoView?.({ block: "center", behavior: "smooth" }));
    const timer = window.setTimeout(() => setHighlighted(""), 1800);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [selectedTaskId, tasks]);
  function changeFilter(value: TransferFilter) {
    setFilter(value);
    if (settings.transfer_remember_filter) localStorage.setItem(filterKey, value);
    else localStorage.removeItem(filterKey);
  }
  return <section className="transfer-center">
    <header className="feature-header"><div><h2>{t("transfers.title")}</h2><p>{t("transfers.subtitle")}</p></div><button disabled={!completed.length} onClick={() => setHidden(new Set(completed))}><Trash2 />{t("transfers.clearCompleted")}</button></header>
    <div className="filter-tabs">{(["all", "active", "completed", "failed"] as const).map((value) => <button className={filter === value ? "active" : ""} key={value} onClick={() => changeFilter(value)}>{t(`filter.${value}`)}</button>)}</div>
    <div className="transfer-list">{visible.length === 0 ? <div className="empty-state"><strong>{t("transfers.empty")}</strong><span>{t("transfers.emptyHint")}</span></div> : visible.map((task) => {
      const progress = task.progress_percent ?? task.progress ?? 0;
      const done = ["completed", "failed", "cancelled"].includes(task.status);
      const ownTask = !task.username || task.username === settings.username;
      return <article ref={(element) => { if (element) cards.current.set(task.id, element); else cards.current.delete(task.id); }} data-task-id={task.id} key={task.id} className={`transfer-card ${task.status} ${highlighted === task.id ? "action-target-highlight" : ""}`}>
        <div className="transfer-summary"><span className="transfer-kind">{t(`transfers.${task.type}`)}{task.username && task.username !== settings.username ? ` · ${task.username}` : ""}</span><div className="transfer-name"><strong>{task.current_file || task.source_paths.map((path) => path.split("/").pop()).join(", ")}</strong><small>{task.source_paths.join(", ")} → {task.destination_path || "—"}</small></div><span className={`status-badge ${task.status}`}>{t(`task.${task.status}`)}</span><div className="transfer-actions">
          {ownTask && can("transfers.pause") && task.status === "running" && <button title={t("transfers.pause")} onClick={() => task.type === "upload" ? uploadControls.pause(task.id) : void run(() => api.pauseTask(task.id))}><Pause /></button>}
          {ownTask && can("transfers.resume") && task.status === "paused" && <button title={t("transfers.resume")} onClick={() => task.type === "upload" ? uploadControls.resume(task.id) : void run(() => api.resumeTask(task.id))}><Play /></button>}
          {ownTask && can("transfers.retry") && ["failed", "cancelled"].includes(task.status) && <button title={t("transfers.retry")} onClick={() => task.type === "upload" ? uploadControls.retry(task.id) : void run(() => api.retryTask(task.id))}><RotateCcw /></button>}
          {ownTask && can("transfers.cancel") && !done && <button title={t("transfers.cancel")} onClick={() => task.type === "upload" ? uploadControls.cancel(task.id) : void run(() => api.cancelTask(task.id))}><X /></button>}
          <button title={t("transfers.details")} onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(task.id)) { next.delete(task.id); if (selectedTaskId === task.id) onSelectedTaskClose?.(); } else next.add(task.id); return next; })}>{expanded.has(task.id) ? <ChevronUp /> : <ChevronDown />}</button>
        </div></div>
        <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>
        <div className="transfer-stats"><span>{Math.round(progress)}%</span><span>{task.speed_human || "0 B/s"}</span><span>{t("transfers.eta")}: {task.eta_human || "—"}</span><span>{task.files_done} / {task.files_total}</span><span>{formatSize(task.bytes_transferred || 0)} / {formatSize(task.total_bytes || 0)}</span></div>
        {expanded.has(task.id) && <div className="transfer-details"><dl><dt>{t("transfers.started")}</dt><dd>{formatDate(task.started_at)}</dd><dt>{t("transfers.priority")}</dt><dd><select disabled={!ownTask || !can("transfers.change_priority")} value={task.priority} onChange={(event) => task.type === "upload" ? uploadControls.setPriority(task.id, Number(event.target.value)) : void run(() => api.setTaskPriority(task.id, Number(event.target.value)))}><option value={-10}>{t("priority.low")}</option><option value={0}>{t("priority.normal")}</option><option value={10}>{t("priority.high")}</option></select></dd><dt>{t("transfers.currentFile")}</dt><dd>{task.current_file || "—"}</dd></dl>{task.error_message && <pre className="error-log">{task.error_message}\n{task.errors?.join("\n")}</pre>}</div>}
      </article>;
    })}</div>
  </section>;
}
