import { Server } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "hosts", moduleId: "hosts-manager", labelKey: "hosts.name", icon: <Server />,
  category: "infrastructure", permission: "modules.view", dependencies: ["ansible", "modules"], minWidth: 900, minHeight: 580,
});
