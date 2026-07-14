import {
  Activity, Boxes, HardDrive, Network, Package, RefreshCw, ServerCog,
  Settings, Share2, Terminal, Users
} from "lucide-react";
import type { AppDefinition, AppId } from "./types";

export const apps: AppDefinition[] = [
  { id: "files", labelKey: "app.fileManager", icon: <HardDrive />, minWidth: 680, minHeight: 440 },
  { id: "transfers", labelKey: "app.transfers", icon: <RefreshCw /> },
  { id: "users", labelKey: "app.users", icon: <Users />, admin: true },
  { id: "groups", labelKey: "app.groups", icon: <Boxes />, admin: true },
  // Kept in the registry so saved windows/localStorage using the legacy AppId
  // restore safely. It is no longer shown as a separate launcher app.
  { id: "mounts", labelKey: "app.networkMounts", icon: <Network />, admin: true, hidden: true },
  { id: "samba", labelKey: "app.samba", icon: <Share2 />, admin: true },
  { id: "services", labelKey: "app.services", icon: <ServerCog />, admin: true },
  { id: "store", labelKey: "app.store", icon: <Package />, admin: true },
  { id: "logs", labelKey: "app.logs", icon: <Terminal />, admin: true },
  { id: "settings", labelKey: "app.settings", icon: <Settings /> },
  { id: "monitor", labelKey: "app.monitor", icon: <Activity /> }
];

export const appById = Object.fromEntries(apps.map((app) => [app.id, app])) as Record<AppId, AppDefinition>;
