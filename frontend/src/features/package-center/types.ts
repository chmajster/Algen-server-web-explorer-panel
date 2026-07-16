export type { AppJob as PackageJob, PackageHistoryItem, PackageManifest, PackageModule, PackagePlan, PackageSource } from "../../api";

export type PackageTab = "all" | "installed" | "updates" | "jobs" | "history" | "sources";
export type PackageAction = "install" | "reinstall" | "update" | "uninstall" | "start" | "stop" | "restart";
