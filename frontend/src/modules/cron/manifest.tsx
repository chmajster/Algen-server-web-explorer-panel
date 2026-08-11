import { CalendarClock } from "lucide-react";
import { managedModuleManifest } from "../../app/registry/rendering";

export default managedModuleManifest({
  id: "cron", moduleId: "cron", labelKey: "cron.name", icon: <CalendarClock />,
  category: "system", permission: "cron.view", dependencies: ["modules"], minWidth: 920, minHeight: 600,
});
