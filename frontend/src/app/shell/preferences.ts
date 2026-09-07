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

export const shellPreferencesClient = {
  get: () => request<ShellPreferences>("/api/shell/preferences", { cache: "no-store" }),
  save: (value: ShellPreferences) => request<ShellPreferences>("/api/shell/preferences", { method: "PUT", body: JSON.stringify(value) }),
  patch: (value: ShellPreferencesPatch) => request<ShellPreferences>("/api/shell/preferences", { method: "PATCH", body: JSON.stringify(value) }),
};
