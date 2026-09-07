import { Bell, CheckCheck, CircleX, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { WebNAS } from "./WebNASShell";
import type { ShellNotification } from "./managers";
import "./notification-center-shell.css";

type Filter = "all" | "unread" | "error" | "warning" | "success" | "info";

export function NotificationCenterBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [items, setItems] = useState<ShellNotification[]>(() => WebNAS.notification.list());
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => WebNAS.notification.subscribe(() => setItems(WebNAS.notification.list())), []);
  useEffect(() => {
    let current: HTMLElement | null = null;
    const find = () => {
      const next = document.querySelector<HTMLElement>(".notification-center");
      if (current === next) return;
      current?.classList.remove("webnas-managed-notification-center");
      current = next;
      current?.classList.add("webnas-managed-notification-center");
      setHost(current);
    };
    find();
    const observer = new MutationObserver(find);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => { observer.disconnect(); current?.classList.remove("webnas-managed-notification-center"); };
  }, []);

  const categories = useMemo(() => [...new Set(items.map((item) => item.category).filter((value): value is string => Boolean(value)))].sort(), [items]);
  const [category, setCategory] = useState<string>("");
  const visible = useMemo(() => items.filter((item) => {
    if (category && item.category !== category) return false;
    if (filter === "unread") return !item.read;
    if (["error", "warning", "success", "info"].includes(filter)) return item.level === filter;
    return true;
  }), [category, filter, items]);

  if (!host) return null;

  return createPortal(<div className="shell-notification-center">
    <header>
      <div><Bell /><span><strong>Powiadomienia</strong><small>{WebNAS.notification.unread()} nieprzeczytanych</small></span></div>
      <div className="shell-notification-header-actions">
        <button type="button" title="Oznacz wszystkie jako przeczytane" aria-label="Oznacz wszystkie jako przeczytane" onClick={() => WebNAS.notification.markAllRead()}><CheckCheck /></button>
        <button type="button" title="Usuń wszystkie" aria-label="Usuń wszystkie" onClick={() => WebNAS.notification.clear()}><Trash2 /></button>
        <button type="button" title="Zamknij" aria-label="Zamknij" onClick={() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))}><X /></button>
      </div>
    </header>
    <div className="shell-notification-filters">
      <select value={filter} onChange={(event) => setFilter(event.target.value as Filter)} aria-label="Filtr powiadomień">
        <option value="all">Wszystkie</option><option value="unread">Nieprzeczytane</option><option value="error">Błędy</option><option value="warning">Ostrzeżenia</option><option value="success">Sukces</option><option value="info">Informacje</option>
      </select>
      <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Kategoria powiadomień">
        <option value="">Wszystkie kategorie</option>{categories.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </div>
    <div className="shell-notification-list">
      {visible.length === 0 && <div className="shell-notification-empty"><Bell />Brak powiadomień.</div>}
      {visible.map((item) => <article key={item.id} className={`${item.level} ${item.read ? "read" : "unread"}`}>
        <button className="shell-notification-main" type="button" onClick={() => WebNAS.notification.markRead(item.id, !item.read)}>
          <span className="shell-notification-dot" aria-hidden="true" />
          <span><strong>{item.title}</strong><small>{item.source} · {new Date(item.timestamp).toLocaleString()}</small><p>{item.body}</p></span>
        </button>
        {item.actions && item.actions.length > 0 && <div className="shell-notification-actions">{item.actions.map((action) => <button key={action.id} type="button" onClick={() => { action.run(); WebNAS.notification.markRead(item.id); }}>{action.label}</button>)}</div>}
        <button className="shell-notification-remove" type="button" aria-label={`Usuń ${item.title}`} onClick={() => WebNAS.notification.remove(item.id)}><CircleX /></button>
      </article>)}
    </div>
  </div>, host);
}
