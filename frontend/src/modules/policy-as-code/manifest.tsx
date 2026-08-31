import { FileCode2 } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const PolicyAsCodeApp = lazy(() => import("./PolicyAsCodeApp").then((loaded) => ({ default: loaded.PolicyAsCodeApp })));

const manifest: FrontendModuleManifest = {
  id: "policy-as-code",
  moduleId: "policy-as-code",
  labelKey: "Policy-as-Code Engine",
  icon: <FileCode2 />,
  category: "security",
  permission: "policy.view",
  minWidth: 1080,
  minHeight: 720,
  render: (context) => lazyView(
    <PolicyAsCodeApp
      permissions={context.profile.permissions}
      language={context.profile.language}
      toast={context.toast}
      t={context.t}
      setDirty={context.setDirty}
    />,
    context.t("status.loading"),
  ),
};

export default manifest;
