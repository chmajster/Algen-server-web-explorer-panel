import { Network } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { LdapManagerApp } from "./LdapManagerApp";

const manifest: FrontendModuleManifest = {
  id: "ldap-manager",
  moduleId: "ldap-manager",
  labelKey: "LDAP Manager",
  icon: <Network />,
  category: "identity",
  permission: "ldap.connections.read",
  minWidth: 1080,
  minHeight: 720,
  render: (context) => (
    <LdapManagerApp
      permissions={context.profile.permissions}
      language={context.profile.language}
      toast={context.toast}
    />
  ),
};

export default manifest;
