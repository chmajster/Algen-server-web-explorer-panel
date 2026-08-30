import { useState } from "react";
import type { ToastFn, Translate } from "../../../app/types";
import { OfflineRepositoryManagerApp } from "./OfflineRepositoryManagerApp";
import { OsRepositoriesApp } from "./OsRepositoriesApp";
import "./offline-repository-manager.css";

export function OsRepositoriesHubApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const canViewOffline = permissions.includes("os-repositories.offline.view");
  const [mode, setMode] = useState<"online" | "offline">("online");

  return <>
    {canViewOffline && <div className="os-repositories-mode-switch" role="tablist" aria-label="Repository mode">
      <button type="button" role="tab" aria-selected={mode === "online"} className={mode === "online" ? "active" : ""} onClick={() => setMode("online")}>Online repositories</button>
      <button type="button" role="tab" aria-selected={mode === "offline"} className={mode === "offline" ? "active" : ""} onClick={() => setMode("offline")}>Offline Repository Manager</button>
    </div>}
    {mode === "offline" && canViewOffline ? <OfflineRepositoryManagerApp permissions={permissions} t={t} toast={toast} /> : <OsRepositoriesApp permissions={permissions} t={t} toast={toast} />}
  </>;
}
