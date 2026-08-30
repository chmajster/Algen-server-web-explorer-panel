import { FileCode2 } from "lucide-react";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import { PolicyAsCodeApp } from "./PolicyAsCodeApp";

const manifest: FrontendModuleManifest = {
  id: "policy-as-code",
  moduleId: "policy-as-code",
  labelKey: "Policy-as-Code Engine",
  icon: <FileCode2 />,
  category: "security",
  permission: "policy.view",
  minWidth: 1080,
  minHeight: 720,
  render: (context) => <PolicyAsCodeApp
    permissions={context.profile.permissions}
    language={context.profile.language}
    toast={context.toast}
    t={context.t}
    setDirty={context.setDirty}
  />,
};

export default manifest;
