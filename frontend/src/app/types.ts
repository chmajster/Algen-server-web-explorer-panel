import type { ReactNode } from "react";

export type AppId =
  | "files"
  | "transfers"
  | "users"
  | "groups"
  | "mounts"
  | "samba"
  | "services"
  | "store"
  | "logs"
  | "settings"
  | "monitor";

export type Theme = "light" | "dark" | "system";
export type Translate = (key: string) => string;
export type ToastFn = (text: string, type?: "ok" | "error") => void;

export type WindowRect = { x: number; y: number; width: number; height: number };
export type WindowInstance = {
  id: string;
  app: AppId;
  rect: WindowRect;
  restoreRect?: WindowRect;
  minimized: boolean;
  zIndex: number;
  initialPath?: string;
};

export type AppDefinition = {
  id: AppId;
  labelKey: string;
  icon: ReactNode;
  admin?: boolean;
  hidden?: boolean;
  minWidth?: number;
  minHeight?: number;
};

export type User = { username: string; home: string };
export type Toast = { id: number; text: string; type: "ok" | "error" };
