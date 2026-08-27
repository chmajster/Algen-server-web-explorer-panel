import type { Translate } from "../../app/types";
import { canManagePackageJob } from "./packageState";
import { PackageJobProgress } from "./PackageJobProgress";
import type { PackageJob } from "./types";

const defaultPackagePermissions = ["modules.install", "modules.update", "modules.uninstall", "modules.configure"];

export function PackageJobs({ jobs, permissions = defaultPackagePermissions, t, onCancel, onRetry }: { jobs: PackageJob[]; permissions?: readonly string[]; t: Translate; onCancel: (job: PackageJob) => void; onRetry: (job: PackageJob) => void }) {
  return <div className="package-job-list">{jobs.length ? jobs.map((job) => {
    const canManage = canManagePackageJob(job.action, permissions);
    return <PackageJobProgress job={job} canCancel={canManage} canRetry={canManage} t={t} onCancel={() => onCancel(job)} onRetry={() => onRetry(job)} key={job.id} />;
  }) : <div className="empty-state"><strong>{t("package.noJobs")}</strong></div>}</div>;
}
