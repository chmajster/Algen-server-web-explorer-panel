import { lazy, Suspense, type ReactNode } from "react";
import type { FrontendModuleManifest } from "./moduleRegistry";

const ModuleApp = lazy(() => import("../../features/modules/ModuleApp").then((loaded) => ({ default: loaded.ModuleApp })));

export function lazyView(node: ReactNode, loadingLabel: string) {
  return <Suspense fallback={<div className="loading-state">{loadingLabel}</div>}>{node}</Suspense>;
}

export function managedModuleManifest(options: Omit<FrontendModuleManifest, "render"> & { moduleId?: string }): FrontendModuleManifest {
  return {
    ...options,
    render: (context) => lazyView(
      <ModuleApp
        moduleId={options.moduleId || context.item.moduleId || ""}
        initialPath={context.item.initialPath}
        deepLink={context.item.deepLink}
        draftKey={`webnas_window_draft_${context.user.username}_${context.item.id}`}
        permissions={context.profile.permissions}
        t={context.t}
        toast={context.toast}
        onOpenFolder={(path) => context.openApp("files", path)}
        onDirtyChange={context.setDirty}
        onDeepLinkClose={context.clearDeepLink}
      />,
      context.t("status.loading"),
    ),
  };
}
