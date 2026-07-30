import type { ReactNode } from "react";

export type AppId =
  | "files"
  | "transfers"
  | "activity"
  | "identity"
  | "users"
  | "groups"
  | "mounts"
  | "samba"
  | "services"
  | "store"
  | "logs"
  | "settings"
  | "monitor"
  | "modules"
  | "access"
  | "containers"
  | "ansible"
  | "hosts"
  | "module";

export type Theme = "light" | "dark" | "system";
export type Translate = (key: string) => string;
export type ToastFn = (text: string, type?: "ok" | "error", category?: "general" | "admin" | "transfer", moduleId?: string) => void;

export type WindowRect = { x: number; y: number; width: number; height: number };
export type WindowDeepLink = {
  type:
    | "transfer"
    | "package-job"
    | "mount-job"
    | "ansible-job"
    | "ansible-scan"
    | "hosts-operation"
    | "network-transaction"
    | "system-update";
  id: string;
  actionKey: string;
  section?: string;
  jobId?: string;
  issuedAt: number;
};
export type WindowInstance = {
  id: string;
  app: AppId;
  rect: WindowRect;
  restoreRect?: WindowRect;
  minimized: boolean;
  zIndex: number;
  initialPath?: string;
  moduleId?: string;
  deepLink?: WindowDeepLink;
};

export type AppDefinition = {
  id: AppId;
  labelKey: string;
  icon: ReactNode;
  admin?: boolean;
  permission?: string;
  permissionAny?: string[];
  hidden?: boolean;
  minWidth?: number;
  minHeight?: number;
};

export type RecentApp = { id: AppId; usedAt: number };

export type User = { username: string; home: string };
export type Toast = { id: number; text: string; type: "ok" | "error"; category?: "general" | "admin" | "transfer"; moduleId?: string };
