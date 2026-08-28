import { KeyRound } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { CredentialsApp } from "./CredentialsApp";
import "./credentials.css";

const credentialsManifest: FrontendModuleManifest = {
  id: "credentials",
  labelKey: "module.section.credentials",
  icon: <KeyRound />,
  category: "infrastructure",
  permission: "hosts-manager.credentials.view",
  dependencies: ["hosts"],
  minWidth: 900,
  minHeight: 580,
  render: (context) => (
    <CredentialsApp
      permissions={context.profile.permissions}
      t={(key) =>
        key === "hosts.credentials.title"
          ? context.t("module.section.credentials")
          : context.t(key)
      }
      toast={context.toast}
    />
  ),
};

export default credentialsManifest;
