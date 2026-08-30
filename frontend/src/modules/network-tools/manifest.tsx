import { Network } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { NetworkToolsApp } from "./NetworkToolsApp";

const manifest: FrontendModuleManifest = {
  id: "network-tools",
  moduleId: "network-tools",
  labelKey: "module.networkTools",
  icon: <Network />,
  category: "network",
  permission: "network_tools.view",
  dependencies: [],
  minWidth: 900,
  minHeight: 600,
  render: (context) => <NetworkToolsApp permissions={context.profile.permissions} language={context.profile.language} toast={context.toast} />,
};
export default manifest;
