import {
  Activity, Boxes, HardDrive, History, Network, Package, RefreshCw, ServerCog,
  Settings, Share2, Terminal, Users, ShieldCheck
} from "lucide-react";
import type { AppDefinition, AppId } from "./types";

export const apps: AppDefinition[] = [
  { id: "files", labelKey: "app.fileManager", icon: <HardDrive />, minWidth: 680, minHeight: 440 },
  { id: "transfers", labelKey: "app.transfers", icon: <RefreshCw /> },
  { id: "activity", labelKey: "app.activity", icon: <History />, minWidth: 720, minHeight: 480 },
  { id: "users", labelKey: "app.users", icon: <Users />, permission: "rbac.manage" },
  { id: "groups", labelKey: "app.groups", icon: <Boxes />, permission: "rbac.manage" },
  // Kept in the registry so saved windows/localStorage using the legacy AppId
  // restore safely. It is no longer shown as a separate launcher app.
  { id: "mounts", labelKey: "app.networkMounts", icon: <Network />, admin: true, hidden: true },
  { id: "samba", labelKey: "app.samba", icon: <Share2 />, permission: "modules.view" },
  { id: "modules", labelKey: "app.modules", icon: <Boxes />, permission: "modules.view", minWidth: 760, minHeight: 500 },
  { id: "access", labelKey: "app.access", icon: <ShieldCheck />, permission: "rbac.manage", minWidth: 760, minHeight: 500 },
  { id: "services", labelKey: "app.services", icon: <ServerCog />, admin: true },
  { id: "store", labelKey: "app.store", icon: <Package />, permission: "modules.install" },
  { id: "logs", labelKey: "app.logs", icon: <Terminal />, permission: "audit.view" },
  { id: "settings", labelKey: "app.settings", icon: <Settings /> },
  { id: "monitor", labelKey: "app.monitor", icon: <Activity /> },
  { id: "module", labelKey: "app.module", icon: <Package />, permission: "modules.view", hidden: true, minWidth: 760, minHeight: 500 }
];

export const appById = Object.fromEntries(apps.map((app) => [app.id, app])) as Record<AppId, AppDefinition>;
