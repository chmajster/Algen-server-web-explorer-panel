export type { AppJob as PackageJob, PackageHistoryItem, PackageManifest, PackageModule, PackagePlan, PackageSource } from "../../api";

export type PackageTab = "all" | "installed" | "updates" | "jobs" | "history" | "sources";
export type PackageAction = "install" | "update" | "uninstall" | "start" | "stop" | "restart";
