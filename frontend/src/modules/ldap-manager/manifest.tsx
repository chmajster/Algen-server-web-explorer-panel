import { Network } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const LdapManagerApp = lazy(() => import("./LdapManagerApp").then((loaded) => ({ default: loaded.LdapManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "ldap-manager",
  moduleId: "ldap-manager",
  labelKey: "LDAP Manager",
  icon: <Network />,
  category: "identity",
  permission: "ldap.connections.read",
  minWidth: 1080,
  minHeight: 720,
  render: (context) => lazyView(
    <LdapManagerApp
      permissions={context.profile.permissions}
      language={context.profile.language}
      toast={context.toast}
    />,
    context.t("status.loading"),
  ),
};

export default manifest;
