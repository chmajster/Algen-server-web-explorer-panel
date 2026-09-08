import { Braces } from "lucide-react";
import { lazy } from "react";

import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const ApiExplorerApp = lazy(() => import("../../features/api/ApiExplorerApp").then((loaded) => ({ default: loaded.ApiExplorerApp })));

export default {
  id: "api",
  labelKey: "API Explorer",
  icon: <Braces />,
  category: "development",
  permission: "modules.view",
  render: (context) => lazyView(<ApiExplorerApp t={context.t} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
