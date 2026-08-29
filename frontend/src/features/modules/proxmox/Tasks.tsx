import { useCallback, useEffect, useState } from "react";
import { api, type ProxmoxTask } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";

export function ProxmoxTasksView({ refreshKey, t, toast }: { refreshKey: number; t: Translate; toast: ToastFn }) {
  const [tasks, setTasks] = useState<ProxmoxTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ProxmoxTask | null>(null);
  const [log, setLog] = useState<Array<Record<string, unknown>>>([]);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const result = await api.proxmoxTasks("", false, 100);
      setTasks(result.tasks);
      if (selected) {
        const updated = result.tasks.find((item) => item.connection_id === selected.connection_id && item.upid === selected.upid);
        if (updated) setSelected(updated);
      }
    } catch (error) {
      if (!quiet) toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [selected, t, toast]);

  useEffect(() => { void refresh(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!tasks.some((item) => item.status === "Queued" || item.status === "Running")) return undefined;
    const timer = window.setInterval(() => void refresh(true), 2000);
    return () => window.clearInterval(timer);
  }, [refresh, tasks]);

  async function open(item: ProxmoxTask) {
    setSelected(item);
    setLog([]);
    try {
      const result = await api.proxmoxTaskLog(item.upid, item.connection_id);
      setLog(result.log);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }
  }

  return <>
    <section className="module-info">
      <header className="module-section-toolbar"><div><h3>Tasks</h3><p>UPID-backed operations are polled until Proxmox reports a terminal state.</p></div><button type="button" onClick={() => void refresh()} disabled={loading}>Refresh</button></header>
      <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Action</th><th>VMID</th><th>Node</th><th>User</th><th>Status</th><th>Progress</th><th>Exit status</th><th>Updated</th></tr></thead><tbody>{tasks.map((item) => <tr key={`${item.connection_id}:${item.upid}`} onClick={() => void open(item)}>
        <td><strong>{item.action}</strong><br /><small>{item.upid}</small></td>
        <td>{item.vmid ?? "—"}</td>
        <td>{item.node || "—"}</td>
        <td>{item.actor}</td>
        <td><span className={`status-badge ${item.status === "Completed" ? "ok" : item.status === "Failed" ? "error" : "neutral"}`}>{item.status}</span></td>
        <td>{item.progress}%</td>
        <td>{item.exitstatus || "—"}</td>
        <td>{new Date(item.updated_at * 1000).toLocaleString()}</td>
      </tr>)}</tbody></table>{!loading && !tasks.length && <div className="empty-state"><strong>No Proxmox tasks recorded.</strong></div>}</div>
    </section>
    {selected && <Modal title={`${selected.action}: ${selected.vmid ?? selected.node}`} onClose={() => setSelected(null)} wide footer={<button type="button" onClick={() => setSelected(null)}>{t("action.close")}</button>}>
      <dl><dt>UPID</dt><dd><code>{selected.upid}</code></dd><dt>Status</dt><dd>{selected.status} · {selected.progress}%</dd><dt>Exit status</dt><dd>{selected.exitstatus || "—"}</dd><dt>Error</dt><dd>{selected.last_error || "—"}</dd></dl>
      <h4>Task log</h4>
      <pre>{log.map((line) => String(line.t ?? line.msg ?? JSON.stringify(line))).join("\n") || "No task log lines."}</pre>
    </Modal>}
  </>;
}
