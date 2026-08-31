import { KeyRound } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";

const SecretsManagerApp = lazy(() => import("./SecretsManagerApp").then((loaded) => ({ default: loaded.SecretsManagerApp })));

const manifest: FrontendModuleManifest = {
  id: "secrets-manager",
  labelKey: "module.secretsManager",
  icon: <KeyRound />,
  category: "infrastructure",
  permission: "secrets-manager.view",
  minWidth: 980,
  minHeight: 620,
  render: (context) => lazyView(
    <SecretsManagerApp
      permissions={context.profile.permissions}
      language={context.profile.language}
      toast={context.toast}
    />,
    context.t("status.loading"),
  ),
};

export default manifest;
