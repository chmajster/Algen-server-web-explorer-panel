import { Terminal } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const LogsApp = lazy(() => import("../../features/logs/LogsApp").then((loaded) => ({ default: loaded.LogsApp })));

export default {
  id: "logs", labelKey: "app.logs", icon: <Terminal />, category: "observability",
  permissionAny: ["logs.view_own", "logs.view_system", "logs.view_kernel", "logs.view_services", "logs.view_webnas", "logs.view_containers", "system.logs"],
  render: (context) => lazyView(<LogsApp permissions={context.profile.permissions} t={context.t} toast={context.toast} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
