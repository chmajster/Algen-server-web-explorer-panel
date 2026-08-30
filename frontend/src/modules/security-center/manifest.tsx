import { ShieldCheck } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { SecurityCenterApp } from "./SecurityCenterApp";

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
  render: (context) => <SecurityCenterApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};
export default manifest;
