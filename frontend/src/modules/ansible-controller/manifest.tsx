import { Workflow } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "ansible", moduleId: "ansible-controller", labelKey: "ansible.name", icon: <Workflow />,
  category: "automation", permission: "modules.view", dependencies: ["modules"], minWidth: 900, minHeight: 580,
});
