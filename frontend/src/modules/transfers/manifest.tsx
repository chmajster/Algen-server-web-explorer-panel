import { RefreshCw } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const TransferCenter = lazy(() => import("../../features/transfers/TransferCenter").then((loaded) => ({ default: loaded.TransferCenter })));

export default {
  id: "transfers", labelKey: "app.transfers", icon: <RefreshCw />, category: "storage",
  permission: "transfers.view_own", dependencies: ["files"],
  render: (context) => lazyView(<TransferCenter tasks={context.tasks} settings={context.profile} selectedTaskId={context.item.deepLink?.type === "transfer" ? context.item.deepLink.id : undefined} t={context.t} toast={context.toast} uploadControls={context.uploadControls} onSelectedTaskClose={context.clearDeepLink} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
