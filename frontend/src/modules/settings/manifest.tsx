import { Settings } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";
import type { SettingsCategory } from "../../features/settings/SettingsApp";
import type { PolicySubject } from "../../features/admin/IdentityApp";

const SettingsApp = lazy(() => import("../../features/settings/SettingsApp").then((loaded) => ({ default: loaded.SettingsAppView })));
const UpdateDetailsPolicyControl = lazy(() => import("../../features/settings/UpdateDetailsPolicyControl").then((loaded) => ({ default: loaded.UpdateDetailsPolicyControl })));
const categories = new Set<SettingsCategory>(["system", "personalization", "files", "transfers", "notifications", "accessibility", "language", "account", "identity", "network", "networkResources", "updates", "policies", "administration", "about"]);
const category = (value?: string): SettingsCategory => value && categories.has(value as SettingsCategory) ? value as SettingsCategory : "system";
const policySubject = (value?: string): PolicySubject | undefined => {
  const match = /^policy:(user|group):(.+)$/.exec(value || "");
  return match ? { type: match[1] as PolicySubject["type"], id: match[2] } : undefined;
};

export default {
  id: "settings", labelKey: "app.settings", icon: <Settings />, category: "system", permission: "settings.view_own",
  render: (context) => {
    const initialSection = category(context.item.initialPath);
    return lazyView(<>
      <SettingsApp settings={context.profile} initialSection={initialSection} initialPolicySubject={policySubject(context.item.moduleId)} deepLink={context.item.deepLink} t={context.t} toast={context.toast} onSettingsChange={context.onSettingsChange} onOpenApp={context.openApp} onDeepLinkClose={context.clearDeepLink} onSectionChange={context.setInitialPath} />
      <UpdateDetailsPolicyControl active={initialSection === "policies"} t={context.t} toast={context.toast} />
    </>, context.t("status.loading"));
  },
} satisfies FrontendModuleManifest;
