import type { AppDefinition, AppId } from "../types";
import { ModuleRegistry, type FrontendModuleManifest } from "./moduleRegistry";
import { discoverFeatureModules } from "./discovery";

export const builtinModules: FrontendModuleManifest[] = discoverFeatureModules();

export const moduleRegistry = new ModuleRegistry(builtinModules);
export const apps: AppDefinition[] = moduleRegistry.apps();
export const appById = Object.fromEntries(apps.map((app) => [app.id, app])) as Record<AppId, AppDefinition>;
