import type { Translate } from "../../app/types";
import { PackageJobProgress } from "./PackageJobProgress";
import type { PackageJob } from "./types";

export function PackageJobs({ jobs, t, onCancel, onRetry }: { jobs: PackageJob[]; t: Translate; onCancel: (job: PackageJob) => void; onRetry: (job: PackageJob) => void }) {
  return <div className="package-job-list">{jobs.length ? jobs.map((job) => <PackageJobProgress job={job} t={t} onCancel={() => onCancel(job)} onRetry={() => onRetry(job)} key={job.id} />) : <div className="empty-state"><strong>{t("package.noJobs")}</strong></div>}</div>;
}
