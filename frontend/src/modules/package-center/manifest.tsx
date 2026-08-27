import { Package } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const PackageCenter = lazy(() => import("../../features/package-center/PackageCenterApp").then((loaded) => ({ default: loaded.PackageCenterApp })));

export default {
  id: "store", labelKey: "app.store", icon: <Package />, category: "system", permission: "modules.view", dependencies: ["modules"],
  render: (context) => lazyView(<PackageCenter selectedJobId={context.item.deepLink?.type === "package-job" ? context.item.deepLink.jobId || context.item.deepLink.id : undefined} permissions={context.profile.permissions} t={context.t} toast={context.toast} onOpenModule={(moduleId) => context.openApp("module", undefined, moduleId)} onSelectedJobClose={context.clearDeepLink} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
