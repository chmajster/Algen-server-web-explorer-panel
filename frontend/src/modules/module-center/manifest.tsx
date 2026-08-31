import { Boxes, Package } from "lucide-react";
import { lazy } from "react";
import { lazyView, managedModuleManifest } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const PackageCenter = lazy(() => import("../../features/package-center/PackageCenterApp").then((loaded) => ({ default: loaded.PackageCenterApp })));

export default [
  {
    id: "modules",
    labelKey: "app.store",
    icon: <Boxes />,
    category: "system",
    permission: "modules.view",
    hidden: true,
    minWidth: 760,
    minHeight: 500,
    render: (context) => lazyView(
      <PackageCenter permissions={context.profile.permissions} desktopShortcutModules={context.desktopShortcutModules} t={context.t} toast={context.toast} onOpenModule={(moduleId) => context.openApp("module", undefined, moduleId)} onToggleDesktopShortcut={context.toggleDesktopModuleShortcut} />,
      context.t("status.loading"),
    ),
  },
  managedModuleManifest({ id: "module", labelKey: "app.module", icon: <Package />, category: "system", permission: "modules.view", hidden: true, minWidth: 760, minHeight: 500 }),
] satisfies FrontendModuleManifest[];
