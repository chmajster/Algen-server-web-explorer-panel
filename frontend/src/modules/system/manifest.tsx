import { Activity } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const MonitorApp = lazy(() => import("../../features/admin/MonitorApp").then((loaded) => ({ default: loaded.MonitorApp })));

export default {
  id: "monitor", labelKey: "app.monitor", icon: <Activity />, category: "observability", permission: "system.status",
  render: (context) => lazyView(<MonitorApp t={context.t} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
