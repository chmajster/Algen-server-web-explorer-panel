import { Boxes, ShieldCheck, Users } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const IdentityApp = lazy(() => import("../../features/admin/IdentityApp").then((loaded) => ({ default: loaded.IdentityApp })));
const SettingsApp = lazy(() => import("../../features/settings/SettingsApp").then((loaded) => ({ default: loaded.SettingsAppView })));
const identityRender = (tab?: "users" | "groups") => (context: Parameters<FrontendModuleManifest["render"]>[0]) => lazyView(<IdentityApp permissions={context.profile.permissions} initialTab={tab} t={context.t} toast={context.toast} onOpenPolicies={(subject) => context.openApp("settings", "policies", `policy:${subject.type}:${subject.id}`)} />, context.t("status.loading"));

export default [
  { id: "identity", labelKey: "app.identity", icon: <Users />, category: "security", permissionAny: ["users.view", "groups.view", "access.view"], minWidth: 800, minHeight: 520, render: identityRender() },
  { id: "users", labelKey: "app.users", icon: <Users />, category: "security", permission: "users.view", hidden: true, render: identityRender("users") },
  { id: "groups", labelKey: "app.groups", icon: <Boxes />, category: "security", permission: "groups.view", hidden: true, render: identityRender("groups") },
  { id: "access", labelKey: "app.access", icon: <ShieldCheck />, category: "security", permission: "access.view", hidden: true, minWidth: 760, minHeight: 500, render: (context) => lazyView(<SettingsApp settings={context.profile} initialSection="policies" t={context.t} toast={context.toast} onSettingsChange={context.onSettingsChange} onOpenApp={context.openApp} />, context.t("status.loading")) },
] satisfies FrontendModuleManifest[];
