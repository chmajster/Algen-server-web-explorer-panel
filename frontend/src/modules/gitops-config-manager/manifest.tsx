import { GitBranch } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const GitOpsConfigManagerApp = lazy(() => import("./GitOpsConfigManagerApp").then((loaded) => ({ default: loaded.GitOpsConfigManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "gitops-config-manager",
  labelKey: "GitOps Config Manager",
  icon: <GitBranch />,
  category: "automation",
  permission: "gitops.view",
  minWidth: 980,
  minHeight: 640,
  render: (context) => lazyView(
    <GitOpsConfigManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
