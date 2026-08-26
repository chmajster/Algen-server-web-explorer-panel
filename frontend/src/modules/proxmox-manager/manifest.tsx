import { Boxes } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "proxmox",
  moduleId: "proxmox-manager",
  labelKey: "Proxmox Manager",
  icon: <Boxes />,
  category: "infrastructure",
  permission: "modules.view",
  dependencies: ["hosts", "modules"],
  minWidth: 980,
  minHeight: 620,
});
