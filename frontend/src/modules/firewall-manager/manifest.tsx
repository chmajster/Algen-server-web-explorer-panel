import { Shield } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { FirewallManagerApp } from "./FirewallManagerApp";

const manifest: FrontendModuleManifest = {
  id: "firewall-manager",
  moduleId: "firewall-manager",
  labelKey: "module.firewallManager",
  icon: <Shield />,
  category: "security",
  permission: "firewall.view",
  dependencies: [],
  minWidth: 920,
  minHeight: 620,
  render: (context) => <FirewallManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};
export default manifest;
