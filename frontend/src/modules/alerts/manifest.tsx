import { BellRing } from "lucide-react";
import { lazy } from "react";

import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const AlertManagerApp = lazy(() => import("../../features/alerts/AlertManagerApp").then((loaded) => ({ default: loaded.AlertManagerApp })));

export default {
  id: "alerts",
  labelKey: "Alert Manager",
  icon: <BellRing />,
  category: "observability",
  permission: "system.status",
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <AlertManagerApp
      locale={context.profile.language}
      canConfigure={context.profile.permissions.includes("settings.edit_system")}
      canAcknowledge={context.profile.permissions.includes("modules.configure")}
    />,
    context.t("status.loading"),
  ),
} satisfies FrontendModuleManifest;
