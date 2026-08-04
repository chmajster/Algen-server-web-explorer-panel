import { ServerCog } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const ServicesApp = lazy(() => import("../../features/admin/SystemApps").then((loaded) => ({ default: loaded.ServicesApp })));

export default {
  id: "services", labelKey: "app.services", icon: <ServerCog />, category: "system", permission: "services.view",
  render: (context) => lazyView(<ServicesApp t={context.t} toast={context.toast} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
