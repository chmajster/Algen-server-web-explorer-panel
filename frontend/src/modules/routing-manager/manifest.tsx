import { Route } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const RoutingManagerApp = lazy(() => import("./RoutingManagerApp").then((loaded) => ({ default: loaded.RoutingManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "routing-manager",
  labelKey: "Routing Manager",
  icon: <Route />,
  category: "network",
  permission: "routing.view",
  minWidth: 1100,
  minHeight: 680,
  render: (context) => lazyView(
    <RoutingManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
