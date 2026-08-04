import { Workflow } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "apmid", moduleId: "apmid", labelKey: "apmid.name", icon: <Workflow />,
  category: "automation", dependencies: ["hosts"], minWidth: 900, minHeight: 580,
});
