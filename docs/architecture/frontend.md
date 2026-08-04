# Frontend

The canonical frontend catalog is assembled by `app/registry/discovery.ts`. Vite discovers `modules/*/manifest.tsx`; `builtinModules.tsx` only constructs the validated `ModuleRegistry`. Each manifest owns its icon, permissions, dependencies, lazy renderer and navigation metadata. Launcher, desktop, taskbar and window rendering consume the same registry; `Desktop.tsx` contains no application switch.

`core/api/transport.ts` owns cookies, CSRF synchronization, base URL handling and structured error decoding. Typed clients live below `modules/<id>/api/client.ts`. The root `api.ts` is a small composition facade with no endpoints or transport logic; it combines independently owned clients for shell code that needs multiple domains.

A frontend module manifest declares presentation metadata, permissions, dependencies, actions, widgets and a lazy renderer. Feature components own view state and module-specific validation. Shared visual primitives remain under `shared` or the existing reusable component directories.
