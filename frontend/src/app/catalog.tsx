import {
  Activity, Boxes, HardDrive, History, Network, Package, RefreshCw, ServerCog,
  Settings, Share2, Terminal, Users, ShieldCheck, Workflow
} from "lucide-react";
import type { AppDefinition, AppId } from "./types";

export const apps: AppDefinition[] = [
  { id: "files", labelKey: "app.fileManager", icon: <HardDrive />, permission: "files.view", minWidth: 680, minHeight: 440 },
  { id: "transfers", labelKey: "app.transfers", icon: <RefreshCw />, permission: "transfers.view_own" },
  { id: "activity", labelKey: "app.activity", icon: <History />, permission: "audit.view_own", minWidth: 720, minHeight: 480 },
  { id: "identity", labelKey: "app.identity", icon: <Users />, permissionAny: ["users.view", "groups.view", "access.view"], minWidth: 800, minHeight: 520 },
  { id: "users", labelKey: "app.users", icon: <Users />, permission: "users.view", hidden: true },
  { id: "groups", labelKey: "app.groups", icon: <Boxes />, permission: "groups.view", hidden: true },
  // Kept in the registry so saved windows/localStorage using the legacy AppId
  // restore safely. It is no longer shown as a separate launcher app.
  { id: "mounts", labelKey: "app.networkMounts", icon: <Network />, permission: "network_resources.view", hidden: true },
  // Legacy AppId retained only so old saved windows restore safely. Samba is
  // opened from Package Center and the shared Modules application now.
  { id: "samba", labelKey: "app.samba", icon: <Share2 />, permission: "modules.view", hidden: true, minWidth: 760, minHeight: 500 },
  { id: "modules", labelKey: "app.modules", icon: <Boxes />, permission: "modules.view", minWidth: 760, minHeight: 500 },
  { id: "containers", labelKey: "app.containers", icon: <Boxes />, permission: "docker.view", minWidth: 900, minHeight: 580 },
  { id: "ansible", labelKey: "ansible.name", icon: <Workflow />, permission: "modules.view", minWidth: 900, minHeight: 580 },
  { id: "access", labelKey: "app.access", icon: <ShieldCheck />, permission: "access.view", hidden: true, minWidth: 760, minHeight: 500 },
  { id: "services", labelKey: "app.services", icon: <ServerCog />, permission: "services.view" },
  { id: "store", labelKey: "app.store", icon: <Package />, permission: "modules.install" },
  { id: "logs", labelKey: "app.logs", icon: <Terminal />, permissionAny: ["logs.view_own", "logs.view_system", "logs.view_kernel", "logs.view_services", "logs.view_webnas", "logs.view_containers", "system.logs"] },
  { id: "settings", labelKey: "app.settings", icon: <Settings />, permission: "settings.view_own" },
  { id: "monitor", labelKey: "app.monitor", icon: <Activity />, permission: "system.status" },
  { id: "module", labelKey: "app.module", icon: <Package />, permission: "modules.view", hidden: true, minWidth: 760, minHeight: 500 }
];

export const appById = Object.fromEntries(apps.map((app) => [app.id, app])) as Record<AppId, AppDefinition>;
