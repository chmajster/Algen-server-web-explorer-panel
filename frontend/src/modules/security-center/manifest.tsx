import { ShieldCheck } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { SecurityCenterApp } from "./SecurityCenterApp";

const manifest: FrontendModuleManifest = {
  id: "security-center",
  labelKey: "Security Center",
  icon: <ShieldCheck />,
  category: "security",
  permission: "security.view",
  dependencies: ["firewall-manager"],
  minWidth: 960,
  minHeight: 640,
  render: (context) => <SecurityCenterApp permissions={context.profile.permissions} toast={context.toast} />,
};
export default manifest;
