import { ListTodo } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const PackageJobWindow = lazy(() => import("../../features/package-center/PackageJobDialog").then((loaded) => ({ default: loaded.PackageJobWindow })));

export default {
  id: "operation-progress",
  labelKey: "package.operationProgress",
  icon: <ListTodo />,
  category: "system",
  permission: "modules.view",
  hidden: true,
  minWidth: 560,
  minHeight: 420,
  render: (context) => lazyView(
    <PackageJobWindow
      jobId={context.item.deepLink?.jobId || context.item.deepLink?.id}
      moduleName={context.item.deepLink?.section}
      t={context.t}
      native
      onClose={context.closeWindow}
    />,
    context.t("status.loading"),
  ),
} satisfies FrontendModuleManifest;
