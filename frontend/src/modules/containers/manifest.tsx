import { Boxes } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "containers", moduleId: "docker", labelKey: "app.containers", icon: <Boxes />,
  category: "applications", permission: "docker.view", dependencies: ["modules"], minWidth: 900, minHeight: 580,
});
