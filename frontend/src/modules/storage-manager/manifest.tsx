import { HardDrive } from "lucide-react";
import { lazy } from "react";

import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const StorageManagerApp = lazy(() => import("../../features/storage/StorageManagerApp").then((loaded) => ({ default: loaded.StorageManagerApp })));

export default {
  id: "storage-manager",
  labelKey: "module.storageManager",
  icon: <HardDrive />,
  category: "infrastructure",
  permission: "modules.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <StorageManagerApp locale={context.profile.language} />,
    context.t("status.loading"),
  ),
} satisfies FrontendModuleManifest;
