import { Boxes, Package } from "lucide-react";
import { lazy } from "react";
import { lazyView, managedModuleManifest } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const ModuleHub = lazy(() => import("../../features/modules/ModuleHub").then((loaded) => ({ default: loaded.ModuleHub })));

export default [
  { id: "modules", labelKey: "app.modules", icon: <Boxes />, category: "system", permission: "modules.view", minWidth: 760, minHeight: 500, render: (context) => lazyView(<ModuleHub t={context.t} toast={context.toast} onOpen={(moduleId) => context.openApp("module", undefined, moduleId)} />, context.t("status.loading")) },
  managedModuleManifest({ id: "module", labelKey: "app.module", icon: <Package />, category: "system", permission: "modules.view", hidden: true, minWidth: 760, minHeight: 500 }),
] satisfies FrontendModuleManifest[];
