# Frontend architecture

## Principles

The frontend remains React + TypeScript + Vite and uses feature-level state. Do not introduce a global state manager for local feature concerns. Application modules are discovered through the existing module registry; new features must not add a parallel registry or a large global context.

The main layers are:

- `src/app/` — desktop composition, window management and application shell.
- `src/modules/` — module manifests and API adapters exposed to the registry.
- `src/features/` — feature UI, feature hooks, domain helpers and form state.
- `src/components/ui/` — WebNAS Design System primitives.
- `src/core/api/` — transport, runtime guards and compatibility contracts.
- `src/generated/` — generated OpenAPI DTO types. Generated files are never edited manually.

## Desktop

`Desktop.tsx` is the public composition root. Runtime orchestration is kept in `DesktopController.tsx`, while reusable desktop concerns live under `app/desktop/` and existing components such as `Taskbar`, `AppLauncher`, `DesktopWindow`, `windowState` and the module registry remain independent.

Prefer explicit props and focused hooks. Persistence helpers must not know how windows are rendered. Module rendering must go through the registry and must not use application-specific `switch` statements.

Large feature modules should be loaded lazily at the manifest boundary when the split removes meaningful code from the initial bundle. DCST and Package Center follow this model.

## DCST

DCST is split by responsibility:

- `api/` — API boundary and API DTO aliases.
- `domain/` — pure transformations and domain calculations.
- `hooks/` — data loading, CRUD state and feature workflows.
- `pages/` — tab-level composition.
- `components/` — editors, tables and object details.
- `DcstApp.tsx` — composition root only.

API DTO, frontend domain model and form state are separate concepts. A generated OpenAPI type can be adapted into a domain model, but feature components should not mutate generated DTOs as form state.

## WebNAS Design System

Reusable primitives live in `src/components/ui/`. Current foundations include `PageHeader`, `PageSection`, `Toolbar`, `Card`, `StatCard`, `DataTable`, `FilterBar`, `SearchInput`, form controls, `Tabs`, badges, progress, loading/error/empty states, `Modal`, `Drawer`, confirmation dialogs, alerts and tooltips.

Design tokens use `--wn-*` CSS variables. Feature code should use tokens instead of inventing feature-local colors, radii, spacing or z-index values when a semantic token exists.

Administrative list screens should normally use:

`PageHeader -> Toolbar/FilterBar -> DataTable -> Drawer or Modal for Create/Edit`.

Use a destructive confirmation for delete, revoke, disable, firewall changes and network changes. Do not force this pattern when an existing interaction is materially better.

## Imports

- Core code must not import business feature internals.
- Cross-feature imports should use public feature/module boundaries rather than another feature's private component tree.
- Generated API code must not import UI code.
- Domain helpers should remain pure where practical.
- Avoid circular imports and `any`; use `unknown` plus narrowing at untrusted boundaries.

## Adding a module

1. Add or reuse a registry manifest under `src/modules/<module>/`.
2. Keep remote I/O in the module/feature API boundary.
3. Put stateful workflows in focused hooks.
4. Compose the screen from Design System components.
5. Add unit/integration tests for non-trivial behavior.
6. Add E2E coverage when the module exposes a critical administrative workflow.
7. Lazy-load the feature only when it meaningfully reduces the initial bundle.
