import { Boxes, ShieldCheck, Users } from "lucide-react";
import { lazy } from "react";
import { lazyView } from "../../app/registry/rendering";
import type { FrontendModuleManifest } from "../../app/registry/moduleRegistry";

const IdentityApp = lazy(() => import("../../features/admin/IdentityApp").then((loaded) => ({ default: loaded.IdentityApp })));
const RbacAccessApp = lazy(() => import("../../features/admin/RbacAccessApp").then((loaded) => ({ default: loaded.RbacAccessApp })));
const identityRender = (tab?: "users" | "groups") => (context: Parameters<FrontendModuleManifest["render"]>[0]) => lazyView(<IdentityApp permissions={context.profile.permissions} initialTab={tab} t={context.t} toast={context.toast} onOpenPolicies={() => context.openApp("access")} />, context.t("status.loading"));

export default [
  { id: "identity", labelKey: "app.identity", icon: <Users />, category: "security", permissionAny: ["users.view", "groups.view", "access.view"], minWidth: 800, minHeight: 520, render: identityRender() },
  { id: "users", labelKey: "app.users", icon: <Users />, category: "security", permission: "users.view", hidden: true, render: identityRender("users") },
  { id: "groups", labelKey: "app.groups", icon: <Boxes />, category: "security", permission: "groups.view", hidden: true, render: identityRender("groups") },
  { id: "access", labelKey: "app.access", icon: <ShieldCheck />, category: "security", permission: "access.view", hidden: true, minWidth: 940, minHeight: 620, render: (context) => lazyView(<RbacAccessApp t={context.t} toast={context.toast} />, context.t("status.loading")) },
] satisfies FrontendModuleManifest[];
