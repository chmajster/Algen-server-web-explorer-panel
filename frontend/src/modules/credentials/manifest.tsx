import { KeyRound } from "lucide-react";
import { lazy } from "react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { lazyView } from "../../app/registry/rendering";
import "./credentials.css";

const CredentialsApp = lazy(() => import("./CredentialsApp").then((loaded) => ({ default: loaded.CredentialsApp })));

/**
 * Compatibility-only surface for restored pre-Secrets-Manager window state.
 * New navigation uses the dedicated Secrets Manager module.
 */
const credentialsManifest: FrontendModuleManifest = {
  id: "credentials",
  labelKey: "Credentials (deprecated)",
  icon: <KeyRound />,
  category: "infrastructure",
  permissionAny: ["secrets-manager.view", "hosts-manager.credentials.view"],
  dependencies: ["hosts"],
  hidden: true,
  minWidth: 900,
  minHeight: 580,
  render: (context) => lazyView(
    <CredentialsApp
      permissions={context.profile.permissions}
      t={(key) =>
        key === "hosts.credentials.title"
          ? "Secrets Manager"
          : context.t(key)
      }
      toast={context.toast}
    />,
    context.t("status.loading"),
  ),
};

export default credentialsManifest;
