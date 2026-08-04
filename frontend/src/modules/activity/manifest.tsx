import { History } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const ActivityCenter = lazy(() => import("../../features/activity/ActivityCenter").then((loaded) => ({ default: loaded.ActivityCenter })));

export default {
  id: "activity", labelKey: "app.activity", icon: <History />, category: "observability",
  permission: "audit.view_own", minWidth: 720, minHeight: 480,
  render: (context) => lazyView(<ActivityCenter locale={context.profile.language} t={context.t} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
