import { Shield } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { DcstApp } from "../../features/dcst/DcstApp";

const manifest: FrontendModuleManifest = {
  id: "dcst",
  labelKey: "DCST",
  icon: <Shield />,
  category: "infrastructure",
  permission: "dcst.read",
  dependencies: ["hosts", "proxmox", "apmid", "modules"],
  minWidth: 1040,
  minHeight: 680,
  render: (context) => <DcstApp permissions={context.profile.permissions} t={context.t} toast={context.toast} />,
};

export default manifest;
