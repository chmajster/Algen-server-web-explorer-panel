import type { Translate } from "../../app/types";
import { PackageJobProgress } from "./PackageJobProgress";
import type { PackageJob } from "./types";

const defaultPackagePermissions = ["modules.install", "modules.update", "modules.uninstall", "modules.configure"];

function canManageJob(job: PackageJob, permissions: readonly string[]): boolean {
  switch (job.action) {
    case "install":
      return permissions.includes("modules.install");
    case "reinstall":
    case "update":
      return permissions.includes("modules.update");
    case "uninstall":
      return permissions.includes("modules.uninstall");
    default:
      return permissions.includes("modules.configure");
  }
}

export function PackageJobs({ jobs, permissions = defaultPackagePermissions, t, onCancel, onRetry }: { jobs: PackageJob[]; permissions?: readonly string[]; t: Translate; onCancel: (job: PackageJob) => void; onRetry: (job: PackageJob) => void }) {
  return <div className="package-job-list">{jobs.length ? jobs.map((job) => {
    const canManage = canManageJob(job, permissions);
    return <PackageJobProgress job={job} canCancel={canManage} canRetry={canManage} t={t} onCancel={() => onCancel(job)} onRetry={() => onRetry(job)} key={job.id} />;
  }) : <div className="empty-state"><strong>{t("package.noJobs")}</strong></div>}</div>;
}
