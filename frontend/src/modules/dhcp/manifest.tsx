import { Network } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "dhcp", moduleId: "dhcp", labelKey: "dhcp.name", icon: <Network />,
  category: "system", permission: "dhcp.view", dependencies: ["modules", "hosts"], minWidth: 960, minHeight: 640,
});
