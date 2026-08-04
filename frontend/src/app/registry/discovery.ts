import type { FrontendModuleManifest } from "./moduleRegistry";

type ManifestModule = { default: FrontendModuleManifest | FrontendModuleManifest[] };

export function discoverFeatureModules(): FrontendModuleManifest[] {
  const modules = import.meta.glob<ManifestModule>("../../modules/*/manifest.tsx", { eager: true });
  return Object.entries(modules)
    .sort(([left], [right]) => left.localeCompare(right))
    .flatMap(([, loaded]) => loaded.default);
}
