import { Network } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const SettingsApp = lazy(() => import("../../features/settings/SettingsApp").then((loaded) => ({ default: loaded.SettingsAppView })));

export default {
  id: "mounts", labelKey: "app.networkMounts", icon: <Network />, category: "storage", permission: "network_resources.view", hidden: true,
  render: (context) => lazyView(<SettingsApp settings={context.profile} initialSection="networkResources" t={context.t} toast={context.toast} onSettingsChange={context.onSettingsChange} onOpenApp={context.openApp} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
