import { KeyRound } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { SecretsManagerApp } from "./SecretsManagerApp";

const manifest: FrontendModuleManifest = {
  id: "secrets-manager",
  labelKey: "Secrets Manager",
  icon: <KeyRound />,
  category: "infrastructure",
  permission: "secrets-manager.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => (
    <SecretsManagerApp
      permissions={context.profile.permissions}
      language={context.profile.language}
      toast={context.toast}
    />
  ),
};

export default manifest;
