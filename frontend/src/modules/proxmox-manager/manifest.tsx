import { Boxes } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const ProxmoxManagerApp = lazy(() =>
  import("../../features/modules/proxmox/ProxmoxManagerApp").then((loaded) => ({
    default: loaded.ProxmoxManagerApp,
  })),
);

const manifest: FrontendModuleManifest = {
  id: "proxmox",
  labelKey: "Proxmox Manager",
  icon: <Boxes />,
  category: "infrastructure",
  permission: "modules.view",
  dependencies: ["hosts", "modules"],
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <ProxmoxManagerApp permissions={context.profile.permissions} t={context.t} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
