import type { AppId, Toast } from "../types";
import type { ViewportMetrics, WindowAction, WindowState } from "../windowState";

export type ShellEvent<T = unknown> = { type: string; detail: T };
export type ShellListener<T = unknown> = (event: ShellEvent<T>) => void;

class EventManager {
  private readonly listeners = new Set<ShellListener>();

  subscribe(listener: ShellListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  protected emit<T>(type: string, detail: T): void {
    const event = { type, detail };
    for (const listener of this.listeners) listener(event);
  }
}

export class WindowManager extends EventManager {
  private state: WindowState | null = null;
  private viewport: ViewportMetrics | null = null;

  bind(state: WindowState, viewport: ViewportMetrics): void {
    this.state = state;
    this.viewport = viewport;
  }

  snapshot(): WindowState | null { return this.state; }
  metrics(): ViewportMetrics | null { return this.viewport; }

  open(app: AppId, options: { initialPath?: string; moduleId?: string } = {}): void {
    this.emit<WindowAction>("dispatch", { type: "open", app, ...options, viewport: this.viewport ?? undefined });
  }

  openOrFocus(app: AppId, deepLink: NonNullable<Extract<WindowAction, { type: "openOrFocus" }>["deepLink"]>, options: { initialPath?: string; moduleId?: string } = {}): void {
    this.emit<WindowAction>("dispatch", { type: "openOrFocus", app, deepLink, ...options, viewport: this.viewport ?? undefined });
  }

  close(id: string): void { this.emit<WindowAction>("dispatch", { type: "close", id }); }
  focus(id: string): void { this.emit<WindowAction>("dispatch", { type: "focus", id }); }
  minimize(id: string): void { this.emit<WindowAction>("dispatch", { type: "minimize", id }); }
  toggleMaximize(id: string): void { if (this.viewport) this.emit<WindowAction>("dispatch", { type: "toggleMaximize", id, viewport: this.viewport }); }
  showDesktop(): void { this.emit("show-desktop", null); }
}

export type NotificationLevel = "info" | "success" | "warning" | "error";
export type ShellNotificationAction = { id: string; label: string; run: () => void };
export type ShellNotification = {
  id: string;
  type: string;
  title: string;
  body: string;
  timestamp: number;
  source: string;
  level: NotificationLevel;
  category?: string;
  read: boolean;
  actions?: ShellNotificationAction[];
};

export class NotificationManager extends EventManager {
  private items: ShellNotification[] = [];
  private readonly maxItems = 250;

  send(input: Omit<ShellNotification, "id" | "timestamp" | "read"> & Partial<Pick<ShellNotification, "id" | "timestamp" | "read">>): ShellNotification {
    const item: ShellNotification = {
      ...input,
      id: input.id || `notification-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      timestamp: input.timestamp ?? Date.now(),
      read: input.read ?? false,
    };
    this.items = [item, ...this.items.filter((existing) => existing.id !== item.id)].slice(0, this.maxItems);
    this.emit("changed", this.list());
    return item;
  }

  ingestToast(toast: Toast): void {
    this.send({
      id: `toast-${toast.id}`,
      type: "toast",
      title: toast.type === "error" ? "WebNAS error" : "WebNAS",
      body: toast.text,
      source: toast.moduleId || "webnas",
      level: toast.type === "error" ? "error" : "success",
      category: toast.category,
    });
  }

  list(): ShellNotification[] { return this.items.map((item) => ({ ...item, actions: item.actions ? [...item.actions] : undefined })); }
  unread(): number { return this.items.filter((item) => !item.read).length; }
  markRead(id: string, read = true): void { this.items = this.items.map((item) => item.id === id ? { ...item, read } : item); this.emit("changed", this.list()); }
  markAllRead(): void { this.items = this.items.map((item) => ({ ...item, read: true })); this.emit("changed", this.list()); }
  remove(id: string): void { this.items = this.items.filter((item) => item.id !== id); this.emit("changed", this.list()); }
  clear(): void { this.items = []; this.emit("changed", this.list()); }
}

export type SearchResult = {
  id: string;
  title: string;
  subtitle?: string;
  category: "application" | "file" | "directory" | "service" | "container" | "setting" | "action";
  keywords?: string[];
  permitted?: () => boolean;
  run: () => void | Promise<void>;
};

export class SearchManager {
  private readonly providers = new Map<string, (query: string) => SearchResult[] | Promise<SearchResult[]>>();

  register(id: string, provider: (query: string) => SearchResult[] | Promise<SearchResult[]>): () => void {
    this.providers.set(id, provider);
    return () => this.providers.delete(id);
  }

  async search(query: string): Promise<SearchResult[]> {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return [];
    const batches = await Promise.all([...this.providers.values()].map((provider) => Promise.resolve(provider(normalized))));
    const results = batches.flat().filter((item) => item.permitted?.() !== false);
    return results.filter((item) => `${item.title} ${item.subtitle || ""} ${(item.keywords || []).join(" ")}`.toLocaleLowerCase().includes(normalized));
  }
}

export class TaskbarManager extends EventManager {
  setBadge(app: string, value: number | null): void { this.emit("badge", { app, value }); }
  pin(app: string): void { this.emit("pin", app); }
  unpin(app: string): void { this.emit("unpin", app); }
  reorder(ids: string[]): void { this.emit("reorder", ids); }
}

export class StartMenuManager extends EventManager {
  open(): void { this.emit("open", null); }
  close(): void { this.emit("close", null); }
  toggle(): void { this.emit("toggle", null); }
  pin(app: string): void { this.emit("pin", app); }
  unpin(app: string): void { this.emit("unpin", app); }
  reorder(ids: string[]): void { this.emit("reorder", ids); }
}

export type DesktopItemPosition = { id: string; x: number; y: number };
export class DesktopManager extends EventManager {
  private selected = new Set<string>();
  select(ids: string[]): void { this.selected = new Set(ids); this.emit("selection", [...this.selected]); }
  selection(): string[] { return [...this.selected]; }
  clearSelection(): void { this.select([]); }
  createFolder(): void { this.emit("new-folder", null); }
  createShortcut(): void { this.emit("new-shortcut", null); }
  sort(mode: "name" | "type" | "date"): void { this.emit("sort", mode); }
  align(): void { this.emit("align", null); }
  positions(items: DesktopItemPosition[]): void { this.emit("positions", items); }
}

export class ClipboardManager extends EventManager {
  private payload: { mode: "copy" | "cut"; items: string[] } | null = null;
  copy(items: string[]): void { this.payload = { mode: "copy", items: [...items] }; this.emit("changed", this.payload); }
  cut(items: string[]): void { this.payload = { mode: "cut", items: [...items] }; this.emit("changed", this.payload); }
  clear(): void { this.payload = null; this.emit("changed", null); }
  get(): { mode: "copy" | "cut"; items: string[] } | null { return this.payload ? { mode: this.payload.mode, items: [...this.payload.items] } : null; }
  paste(target?: string): void { if (this.payload) this.emit("paste", { ...this.payload, target }); }
}

export class ActivityManager extends EventManager {
  create(type: string, detail: unknown): void { this.emit(type, detail); }
}

export type AppManifest = {
  id: string;
  name: string;
  description?: string;
  version: string;
  icon?: string;
  entry: string;
  permissions: string[];
  multiWindow: boolean;
  category: string;
  enabled?: boolean;
};

const safeId = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const safeEntry = /^\/(?:[a-zA-Z0-9._~-]+\/?)*$/;
export class ApplicationManager extends EventManager {
  private manifests = new Map<string, AppManifest>();

  validate(manifest: AppManifest): AppManifest {
    if (!safeId.test(manifest.id)) throw new Error("Invalid application id");
    if (!manifest.name.trim() || manifest.name.length > 120) throw new Error("Invalid application name");
    if (!safeEntry.test(manifest.entry) || manifest.entry.includes("..")) throw new Error("Invalid application entry");
    if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(manifest.version)) throw new Error("Invalid application version");
    if (!Array.isArray(manifest.permissions) || manifest.permissions.some((value) => !/^[a-z0-9._:-]{1,80}$/i.test(value))) throw new Error("Invalid application permissions");
    return { ...manifest, permissions: [...manifest.permissions] };
  }

  register(manifest: AppManifest): void { const valid = this.validate(manifest); this.manifests.set(valid.id, valid); this.emit("changed", this.list()); }
  unregister(id: string): void { this.manifests.delete(id); this.emit("changed", this.list()); }
  list(): AppManifest[] { return [...this.manifests.values()].map((item) => ({ ...item, permissions: [...item.permissions] })); }
  get(id: string): AppManifest | undefined { const value = this.manifests.get(id); return value ? { ...value, permissions: [...value.permissions] } : undefined; }
  open(id: string): void { if (!this.manifests.has(id)) throw new Error(`Unknown application: ${id}`); this.emit("open", id); }
}

export class SessionManager extends EventManager {
  lock(): void { this.emit("lock", null); }
  logout(): void { this.emit("logout", null); }
  restartWebNAS(): void { this.emit("restart-webnas", null); }
  restartHost(): void { this.emit("restart-host", null); }
  shutdownHost(): void { this.emit("shutdown-host", null); }
}
