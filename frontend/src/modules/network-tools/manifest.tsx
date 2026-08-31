import { Network } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const NetworkToolsApp = lazy(() => import("./NetworkToolsApp").then((loaded) => ({ default: loaded.NetworkToolsApp })));

const manifest: FrontendModuleManifest = {
  id: "network-tools",
  moduleId: "network-tools",
  labelKey: "module.networkTools",
  icon: <Network />,
  category: "network",
  permission: "network_tools.view",
  dependencies: [],
  minWidth: 900,
  minHeight: 600,
  render: (context) => lazyView(
    <NetworkToolsApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
