import { Shield } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const DcstApp = lazy(() => import("../../features/dcst/DcstApp").then((loaded) => ({ default: loaded.DcstApp })));

const manifest: FrontendModuleManifest = {
  id: "dcst",
  labelKey: "DCST",
  icon: <Shield />,
  category: "infrastructure",
  permission: "dcst.read",
  dependencies: ["hosts", "proxmox", "apmid", "modules"],
  minWidth: 1040,
  minHeight: 680,
  render: (context) => lazyView(
    <DcstApp permissions={context.profile.permissions} t={context.t} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
