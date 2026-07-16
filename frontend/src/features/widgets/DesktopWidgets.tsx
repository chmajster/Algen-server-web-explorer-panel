import { Activity, AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bell, Cpu, Grip, HardDrive, MemoryStick, Move, Network, Pin, PinOff, Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DesktopWidget, type DesktopWidgetId, type ModuleSummary, type ResourceDashboard, type SettingsMe, type SettingsPatch, type Task } from "../../api";
import type { Toast, Translate } from "../../app/types";

const IDS: DesktopWidgetId[] = ["cpu", "ram", "disks", "transfers", "services", "alerts"];

export function DesktopWidgets({ profile, tasks, toasts, t, onSettingsChange }: { profile: SettingsMe; tasks: Task[]; toasts: Toast[]; t: Translate; onSettingsChange: (patch: SettingsPatch) => Promise<void> }) {
  const [layout, setLayout] = useState(profile.desktop_widgets);
  const [resources, setResources] = useState<ResourceDashboard | null>(null);
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [editing, setEditing] = useState(false);
  const board = useRef<HTMLDivElement>(null);
  const layoutRef = useRef(layout);
  const gesture = useRef<{ id: DesktopWidgetId; mode: "move" | "resize"; startX: number; startY: number; widget: DesktopWidget } | null>(null);
  useEffect(() => { setLayout(profile.desktop_widgets); }, [profile.desktop_widgets]);
  useEffect(() => { layoutRef.current = layout; }, [layout]);
  const refresh = useCallback(async () => {
    if (!profile.widgets_enabled) return;
    try { setResources(await api.resources()); } catch { /* Monitoring application surfaces connectivity details. */ }
    if (profile.permissions.includes("modules.view")) {
      try { setModules(await api.modules()); } catch { /* A widget must not interrupt the desktop. */ }
    }
  }, [profile.permissions, profile.widgets_enabled]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => {
    const move = (event: PointerEvent) => {
      const active = gesture.current; const root = board.current;
      if (!active || !root) return;
      const cell = root.clientWidth / 12; const row = 86;
      const dx = Math.round((event.clientX - active.startX) / cell); const dy = Math.round((event.clientY - active.startY) / row);
      setLayout((current) => current.map((item) => item.id !== active.id ? item : active.mode === "move" ? { ...item, x: Math.max(0, Math.min(12 - item.width, active.widget.x + dx)), y: Math.max(0, Math.min(20, active.widget.y + dy)) } : { ...item, width: Math.max(2, Math.min(12 - item.x, active.widget.width + dx)), height: Math.max(1, Math.min(6, active.widget.height + dy)) }));
    };
    const up = () => { if (!gesture.current) return; gesture.current = null; void onSettingsChange({ desktop_widgets: layoutRef.current }).catch(() => setLayout(profile.desktop_widgets)); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [onSettingsChange, profile.desktop_widgets]);
  if (!profile.widgets_enabled) return null;

  function begin(event: React.PointerEvent, item: DesktopWidget, mode: "move" | "resize") { if (!editing) return; event.preventDefault(); gesture.current = { id: item.id, mode, startX: event.clientX, startY: event.clientY, widget: item }; }
  function patchWidget(id: DesktopWidgetId, patch: Partial<DesktopWidget>) { const next = layout.map((item) => item.id === id ? { ...item, ...patch } : item); setLayout(next); void onSettingsChange({ desktop_widgets: next }).catch(() => setLayout(profile.desktop_widgets)); }
  function nudge(item: DesktopWidget, dx: number, dy: number) { patchWidget(item.id, { x: Math.max(0, Math.min(12 - item.width, item.x + dx)), y: Math.max(0, Math.min(20, item.y + dy)) }); }
  function content(id: DesktopWidgetId) {
    if (id === "cpu") return <><strong>{resources?.cpu_percent == null ? "—" : `${Math.round(resources.cpu_percent)}%`}</strong><span>{resources?.cpu_logical_cores || 0} {t("widgets.cores")}</span><Meter value={resources?.cpu_percent || 0} /></>;
    if (id === "ram") return <><strong>{Math.round(resources?.ram.percent || 0)}%</strong><span>{bytes(resources?.ram.used)} / {bytes(resources?.ram.total)}</span><Meter value={resources?.ram.percent || 0} /></>;
    if (id === "disks") { const disks = resources?.mountpoints.length ? resources.mountpoints : resources?.allowed_roots || []; return <div className="widget-list">{disks.slice(0, 4).map((disk) => <div key={disk.path}><span>{disk.mountpoint || disk.path}</span><b>{Math.round(disk.percent)}%</b></div>)}</div>; }
    if (id === "transfers") { const active = tasks.filter((task) => ["queued", "running", "paused"].includes(task.status)); return <><strong>{active.length}</strong><span>{t("widgets.activeTransfers")}</span><div className="widget-list">{active.slice(0, 3).map((task) => <div key={task.id}><span>{task.current_file || task.type}</span><b>{Math.round(task.progress_percent || 0)}%</b></div>)}</div></>; }
    if (id === "services") return <div className="widget-list">{modules.slice(0, 5).map((module) => <div key={module.id}><span>{module.manifest.name}</span><b className={module.module_status.health}>{t(`module.health.${module.module_status.health}`)}</b></div>)}{!modules.length && <span>{t("widgets.noServices")}</span>}</div>;
    const alerts = [...(resources?.alerts || []).map((alert) => ({ id: `${alert.code}:${alert.target}`, text: `${alert.code}: ${alert.target}`, severity: alert.severity })), ...toasts.filter((item) => item.type === "error").map((item) => ({ id: `toast:${item.id}`, text: item.text, severity: "critical" }))];
    return <div className="widget-list">{alerts.slice(-5).reverse().map((alert) => <div key={alert.id}><AlertTriangle /><span>{alert.text}</span><b>{alert.severity}</b></div>)}{!alerts.length && <span>{t("widgets.noAlerts")}</span>}</div>;
  }
  return <section className={`desktop-widget-layer ${editing ? "editing" : ""}`} aria-label={t("widgets.title")}>
    <button className="widget-edit-toggle" type="button" aria-pressed={editing} onClick={() => setEditing((value) => !value)}><Settings2 />{editing ? t("widgets.finish") : t("widgets.customize")}</button>
    {editing && <aside className="widget-picker" aria-label={t("widgets.visibility")}>{IDS.map((id) => { const item = layout.find((widget) => widget.id === id); return <button type="button" key={id} aria-pressed={item?.visible} onClick={() => item && patchWidget(id, { visible: !item.visible })}>{item?.visible ? <Pin /> : <PinOff />}{t(`widgets.${id}`)}</button>; })}</aside>}
    <div className="desktop-widget-grid" ref={board}>{layout.filter((item) => item.visible).map((item) => <article className="desktop-widget" key={item.id} style={{ gridColumn: `${item.x + 1} / span ${item.width}`, gridRow: `${item.y + 1} / span ${item.height}` }}>
      <header onPointerDown={(event) => begin(event, item, "move")}><span>{icon(item.id)}{t(`widgets.${item.id}`)}</span>{editing && <><Grip /><button type="button" title={t("widgets.hide")} onClick={() => patchWidget(item.id, { visible: false })}><PinOff /></button></>}</header>
      <div className="widget-content">{content(item.id)}</div>
      {editing && <><div className="widget-keyboard-controls"><button title={t("widgets.left")} onClick={() => nudge(item, -1, 0)}><ArrowLeft /></button><button title={t("widgets.right")} onClick={() => nudge(item, 1, 0)}><ArrowRight /></button><button title={t("widgets.up")} onClick={() => nudge(item, 0, -1)}><ArrowUp /></button><button title={t("widgets.down")} onClick={() => nudge(item, 0, 1)}><ArrowDown /></button></div><button className="widget-resize-handle" type="button" title={t("widgets.resize")} onPointerDown={(event) => begin(event, item, "resize")}><Move /></button></>}
    </article>)}</div>
  </section>;
}

function Meter({ value }: { value: number }) { return <div className="widget-meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>; }
function bytes(value?: number) { if (!value) return "0 B"; const units = ["B", "KiB", "MiB", "GiB", "TiB"]; const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))); return `${(value / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`; }
function icon(id: DesktopWidgetId) { return id === "cpu" ? <Cpu /> : id === "ram" ? <MemoryStick /> : id === "disks" ? <HardDrive /> : id === "transfers" ? <Network /> : id === "services" ? <Activity /> : <Bell />; }
