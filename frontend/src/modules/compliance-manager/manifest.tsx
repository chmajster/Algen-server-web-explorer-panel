import { ClipboardCheck } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { ComplianceManagerApp } from "./ComplianceManagerApp";

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
  render: (context) => <ComplianceManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};

export default manifest;
