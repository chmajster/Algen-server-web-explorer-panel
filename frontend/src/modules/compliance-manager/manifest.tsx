import { ClipboardCheck } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const ComplianceManagerApp = lazy(() => import("./ComplianceManagerApp").then((loaded) => ({ default: loaded.ComplianceManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "compliance-manager",
  moduleId: "compliance-manager",
  labelKey: "Compliance Manager",
  icon: <ClipboardCheck />,
  category: "security",
  permission: "compliance.view",
  dependencies: ["firewall-manager"],
  minWidth: 1040,
  minHeight: 680,
  render: (context) => lazyView(
    <ComplianceManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
