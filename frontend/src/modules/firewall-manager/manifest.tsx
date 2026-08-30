import { Shield } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { FirewallManagerApp } from "./FirewallManagerApp";

const manifest: FrontendModuleManifest = {
  id: "firewall-manager",
  labelKey: "Firewall Manager",
  icon: <Shield />,
  category: "security",
  permission: "firewall.view",
  dependencies: [],
  minWidth: 920,
  minHeight: 620,
  render: (context) => <FirewallManagerApp permissions={context.profile.permissions} toast={context.toast} />,
};
export default manifest;
