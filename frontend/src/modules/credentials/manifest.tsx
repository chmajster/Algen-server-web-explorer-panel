import { KeyRound } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { CredentialsApp } from "./CredentialsApp";

const credentialsManifest: FrontendModuleManifest = {
  id: "credentials",
  labelKey: "hosts.credentials.title",
  icon: <KeyRound />,
  category: "infrastructure",
  permission: "hosts-manager.credentials.view",
  dependencies: ["hosts"],
  minWidth: 900,
  minHeight: 580,
  render: (context) => (
    <CredentialsApp
      permissions={context.profile.permissions}
      t={context.t}
      toast={context.toast}
    />
  ),
};

export default credentialsManifest;
