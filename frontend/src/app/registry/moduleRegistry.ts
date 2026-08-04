import type { ReactNode } from "react";
import type { SettingsMe, SettingsPatch, Task } from "../../core/api/contracts";
import type { UploadControls } from "../../features/transfers/useUploadManager";
import type { AppDefinition, AppId, ToastFn, Translate, User, WindowInstance } from "../types";

export type AppRenderContext = {
  item: WindowInstance;
  user: User;
  profile: SettingsMe;
  tasks: Task[];
  uploadControls: UploadControls;
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
  openApp: (app: AppId, initialPath?: string, moduleId?: string) => void;
  clearDeepLink: () => void;
  setDirty: (dirty: boolean) => void;
  setInitialPath: (path: string) => void;
};

export type FrontendModuleManifest = AppDefinition & {
  version?: string;
  category?: string;
  dependencies?: AppId[];
  actions?: string[];
  widgets?: string[];
  render: (context: AppRenderContext) => ReactNode;
};

export class ModuleRegistry {
  readonly #modules = new Map<AppId, FrontendModuleManifest>();

  constructor(manifests: FrontendModuleManifest[] = []) {
    manifests.forEach((manifest) => this.register(manifest));
    this.validateDependencies();
  }

  register(manifest: FrontendModuleManifest) {
    if (!/^[a-z][a-z0-9-]{1,63}$/.test(manifest.id)) throw new Error(`Invalid module id: ${manifest.id}`);
    if (this.#modules.has(manifest.id)) throw new Error(`Duplicate module id: ${manifest.id}`);
    this.#modules.set(manifest.id, Object.freeze({ version: "1.0.0", category: "application", ...manifest }));
  }

  get(id: AppId) { return this.#modules.get(id); }
  apps() { return [...this.#modules.values()]; }
  visibleApps() { return this.apps().filter((manifest) => !manifest.hidden); }

  validateDependencies() {
    for (const manifest of this.#modules.values()) {
      for (const dependency of manifest.dependencies || []) {
        if (!this.#modules.has(dependency)) throw new Error(`Module ${manifest.id} requires missing module ${dependency}`);
      }
    }
  }

  availableFor(id: AppId, permissions: readonly string[], isAdmin: boolean) {
    const manifest = this.#modules.get(id);
    if (!manifest || (manifest.admin && !isAdmin)) return false;
    if (manifest.permission && !permissions.includes(manifest.permission)) return false;
    return !manifest.permissionAny || manifest.permissionAny.some((permission) => permissions.includes(permission));
  }

  render(id: AppId, context: AppRenderContext) {
    const manifest = this.#modules.get(id);
    if (!manifest) throw new Error(`Unknown module: ${id}`);
    return manifest.render(context);
  }
}
