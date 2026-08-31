import { ListChecks } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const JobQueueManagerApp = lazy(() => import("./JobQueueManagerApp").then((loaded) => ({ default: loaded.JobQueueManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "job-queue-manager",
  labelKey: "Job Queue Manager",
  icon: <ListChecks />,
  category: "system",
  permission: "jobs.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <JobQueueManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
