import { Shield } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const FirewallManagerApp = lazy(() => import("./FirewallManagerApp").then((loaded) => ({ default: loaded.FirewallManagerApp })));

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
  render: (context) => lazyView(
    <FirewallManagerApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
    context.t("status.loading"),
  ),
};

export default manifest;
