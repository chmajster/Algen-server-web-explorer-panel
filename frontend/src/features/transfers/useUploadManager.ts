import { useCallback, useRef, useState } from "react";
import { api, type Task } from "../../api";

type RuntimeUpload = {
  file: File;
  path: string;
  sessionId?: string;
  offset: number;
  startedAt: number;
  controller?: AbortController;
  pauseRequested?: boolean;
  cancelRequested?: boolean;
};

export type UploadControls = {
  add: (files: File[], path: string) => void;
  pause: (id: string) => void;
  resume: (id: string) => void;
  cancel: (id: string) => void;
  retry: (id: string) => void;
  setPriority: (id: string, priority: number) => void;
};

function taskFor(id: string, file: File, path: string): Task {
  const now = Date.now() / 1000;
  return {
    id, type: "upload", op: "upload", status: "queued", priority: 0, created_at: now,
    source_paths: [file.name], destination_path: path, started_at: null, finished_at: null, paused_at: null,
    bytes_transferred: 0, total_bytes: file.size, progress_percent: 0, progress: 0,
    speed_bps: 0, speed_human: "0 B/s", average_speed_bps: 0, average_speed_human: "0 B/s",
    eta_seconds: null, eta_human: "—", current_file: file.name, files_done: 0, files_total: 1,
    rsync_exit_code: null, error_message: "", log_tail: [], stderr_tail: [], command_preview: [], retry_count: 0, errors: []
  };
}

function humanSpeed(value: number) {
  if (value < 1024) return `${Math.round(value)} B/s`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB/s`;
  return `${(value / 1024 ** 2).toFixed(1)} MB/s`;
}

export function useUploadManager(): { tasks: Task[]; controls: UploadControls } {
  const [tasks, setTasks] = useState<Task[]>([]);
  const runtime = useRef(new Map<string, RuntimeUpload>());
  const patchTask = useCallback((id: string, patch: Partial<Task>) => setTasks((current) => current.map((task) => task.id === id ? { ...task, ...patch } : task)), []);

  const run = useCallback(async (id: string) => {
    const active = runtime.current.get(id);
    if (!active) return;
    active.pauseRequested = false;
    active.cancelRequested = false;
    patchTask(id, { status: "running", started_at: active.startedAt / 1000, paused_at: null, error_message: "" });
    try {
      if (!active.sessionId) {
        const session = await api.startUpload(active.path, active.file);
        active.sessionId = session.upload_id;
        active.offset = session.offset;
      }
      const chunkSize = 1024 * 1024;
      while (active.offset < active.file.size) {
        if (active.pauseRequested || active.cancelRequested) throw new Error("Upload interrupted");
        const controller = new AbortController();
        active.controller = controller;
        const chunk = active.file.slice(active.offset, Math.min(active.offset + chunkSize, active.file.size));
        const chunkStarted = Date.now();
        const result = await api.uploadChunk(active.sessionId, active.offset, chunk, controller.signal);
        const elapsed = Math.max(.001, (Date.now() - chunkStarted) / 1000);
        active.offset = result.offset;
        const speed = chunk.size / elapsed;
        const average = active.offset / Math.max(.001, (Date.now() - active.startedAt) / 1000);
        const remaining = Math.max(0, active.file.size - active.offset);
        const eta = average > 0 ? remaining / average : null;
        const progress = active.file.size ? active.offset / active.file.size * 100 : 100;
        patchTask(id, { bytes_transferred: active.offset, progress, progress_percent: progress, speed_bps: speed, speed_human: humanSpeed(speed), average_speed_bps: average, average_speed_human: humanSpeed(average), eta_seconds: eta, eta_human: eta === null ? "—" : `${Math.ceil(eta)}s` });
      }
      patchTask(id, { status: "completed", progress: 100, progress_percent: 100, bytes_transferred: active.file.size, files_done: 1, finished_at: Date.now() / 1000, speed_bps: 0, speed_human: "0 B/s", eta_seconds: 0, eta_human: "0s" });
      runtime.current.delete(id);
    } catch (error) {
      if (active.cancelRequested) {
        if (active.sessionId) void api.cancelUpload(active.sessionId).catch(() => undefined);
        patchTask(id, { status: "cancelled", finished_at: Date.now() / 1000 });
      } else if (active.pauseRequested) {
        patchTask(id, { status: "paused", paused_at: Date.now() / 1000, speed_bps: 0, speed_human: "0 B/s" });
      } else {
        const detail = error instanceof Error ? error.message : "Upload failed";
        patchTask(id, { status: "failed", error_message: detail, errors: [detail], finished_at: Date.now() / 1000 });
      }
    }
  }, [patchTask]);

  const add = useCallback((files: File[], path: string) => {
    files.forEach((file, index) => {
      const id = `upload-${Date.now()}-${index}-${Math.random().toString(16).slice(2)}`;
      runtime.current.set(id, { file, path, offset: 0, startedAt: Date.now() });
      setTasks((current) => [...current, taskFor(id, file, path)]);
      setTimeout(() => void run(id), 0);
    });
  }, [run]);
  const pause = useCallback((id: string) => { const active = runtime.current.get(id); if (!active) return; active.pauseRequested = true; active.controller?.abort(); }, []);
  const resume = useCallback((id: string) => { if (runtime.current.has(id)) void run(id); }, [run]);
  const cancel = useCallback((id: string) => {
    const active = runtime.current.get(id); if (!active) return;
    active.cancelRequested = true; active.controller?.abort();
    if (active.sessionId) void api.cancelUpload(active.sessionId).catch(() => undefined);
    patchTask(id, { status: "cancelled", finished_at: Date.now() / 1000 });
  }, [patchTask]);
  const retry = useCallback((id: string) => {
    const active = runtime.current.get(id); if (!active) return;
    if (active.sessionId) void api.cancelUpload(active.sessionId).catch(() => undefined);
    active.sessionId = undefined; active.offset = 0; active.startedAt = Date.now(); active.pauseRequested = false; active.cancelRequested = false;
    setTasks((current) => current.map((task) => task.id === id ? { ...taskFor(id, active.file, active.path), retry_count: task.retry_count + 1 } : task));
    void run(id);
  }, [run]);
  const setPriority = useCallback((id: string, priority: number) => patchTask(id, { priority }), [patchTask]);
  return { tasks, controls: { add, pause, resume, cancel, retry, setPriority } };
}
