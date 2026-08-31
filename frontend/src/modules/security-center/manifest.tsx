import { ShieldCheck } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const SecurityCenterApp = lazy(() => import("./SecurityCenterApp").then((loaded) => ({ default: loaded.SecurityCenterApp })));

const manifest: FrontendModuleManifest = {
  id: "security-center",
  moduleId: "security-center",
  labelKey: "module.securityCenter",
  icon: <ShieldCheck />,
  category: "security",
  permission: "security.view",
  dependencies: ["firewall-manager"],
  minWidth: 960,
  minHeight: 640,
  render: (context) => lazyView(
    <SecurityCenterApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
