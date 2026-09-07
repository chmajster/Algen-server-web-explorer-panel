import { request } from "../../core/api/transport";

export type ShellPoint = { x: number; y: number };
export type ShellSize = { width: number; height: number };
export type ShellDesktopEntry = {
  id: string;
  kind: "app" | "module" | "file" | "directory" | "url" | "folder";
  name: string;
  target: string;
  position: ShellPoint;
  parent_id?: string | null;
  created_at: number;
};
export type ShellWidgetState = { id: string; position: ShellPoint; size: ShellSize; visible: boolean };
export type PersistedShellWindow = {
  id: string;
  app: string;
  x: number;
  y: number;
  width: number;
  height: number;
  minimized: boolean;
  maximized: boolean;
  restore_x?: number | null;
  restore_y?: number | null;
  restore_width?: number | null;
  restore_height?: number | null;
  initial_path?: string | null;
  module_id?: string | null;
};
export type ShellPreferences = {
  version: number;
  desktop: Record<string, unknown>;
  desktop_entries: ShellDesktopEntry[];
  taskbar_order: string[];
  start_order: string[];
  start_hidden: string[];
  recent_files: string[];
  windows: PersistedShellWindow[];
  widgets: ShellWidgetState[];
  notifications: Record<string, unknown>;
  mobile: Record<string, unknown>;
};
export type ShellPreferencesPatch = Partial<ShellPreferences>;

export const defaultShellPreferences: ShellPreferences = {
  version: 1,
  desktop: {},
  desktop_entries: [],
  taskbar_order: [],
  start_order: [],
  start_hidden: [],
  recent_files: [],
  windows: [],
  widgets: [],
  notifications: {},
  mobile: {},
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function array<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

export function normalizeShellPreferences(value: unknown): ShellPreferences {
  const source = record(value);
  return {
    version: typeof source.version === "number" && Number.isFinite(source.version) ? source.version : 1,
    desktop: record(source.desktop),
    desktop_entries: array<ShellDesktopEntry>(source.desktop_entries),
    taskbar_order: array<string>(source.taskbar_order).filter((item): item is string => typeof item === "string"),
    start_order: array<string>(source.start_order).filter((item): item is string => typeof item === "string"),
    start_hidden: array<string>(source.start_hidden).filter((item): item is string => typeof item === "string"),
    recent_files: array<string>(source.recent_files).filter((item): item is string => typeof item === "string"),
    windows: array<PersistedShellWindow>(source.windows),
    widgets: array<ShellWidgetState>(source.widgets),
    notifications: record(source.notifications),
    mobile: record(source.mobile),
  };
}

async function getPreferences() {
  return normalizeShellPreferences(await request<unknown>("/api/shell/preferences", { cache: "no-store" }));
}

async function savePreferences(value: ShellPreferences) {
  return normalizeShellPreferences(await request<unknown>("/api/shell/preferences", { method: "PUT", body: JSON.stringify(value) }));
}

async function patchPreferences(value: ShellPreferencesPatch) {
  return normalizeShellPreferences(await request<unknown>("/api/shell/preferences", { method: "PATCH", body: JSON.stringify(value) }));
}

export const shellPreferencesClient = {
  get: getPreferences,
  save: savePreferences,
  patch: patchPreferences,
};
