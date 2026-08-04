import { Share2 } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "samba", moduleId: "samba", labelKey: "app.samba", icon: <Share2 />,
  category: "storage", permission: "modules.view", dependencies: ["modules"], hidden: true, minWidth: 760, minHeight: 500,
});
