import { Boxes } from "lucide-react";
import { ProxmoxManagerApp } from "../../features/modules/proxmox/ProxmoxManagerApp";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const manifest: FrontendModuleManifest = {
  id: "proxmox",
  labelKey: "Proxmox Manager",
  icon: <Boxes />,
  category: "infrastructure",
  permission: "modules.view",
  dependencies: ["hosts", "modules"],
  minWidth: 980,
  minHeight: 620,
  render: (context) => <ProxmoxManagerApp permissions={context.profile.permissions} t={context.t} toast={context.toast} />,
};

export default manifest;
