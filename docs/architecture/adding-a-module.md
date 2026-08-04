# Adding a module

## Backend

Create `backend/app/modules/builtin/example/manifest.yaml`:

```yaml
id: example
name: Example
version: 1.0.0
category: tools
icon: box
permissions: [example.view]
routers: [app.modules.example.api.router:router]
dependencies: []
capabilities: [read]
menu: [{id: example, label: example.name, icon: box, permission: example.view}]
```

Create the feature package. Add only layers that have a real responsibility:

```text
modules/example/
  domain/models.py       # framework-free entities
  domain/ports.py        # repository/system protocols
  application/service.py # commands and queries
  infrastructure/store.py
  api/schemas.py
  api/router.py           # thin HTTP mapping
```

The router exports `router: APIRouter`. The application service receives ports in its constructor. It raises `DomainError`; it does not raise `HTTPException`. No central router file is edited.

## Frontend

Create `frontend/src/modules/example` with `api/client.ts`, `manifest.tsx`, pages and tests. The typed client imports `request` from `core/api/transport`:

```ts
type Example = { id: string; name: string };
export const exampleClient = { list: () => request<Example[]>("/api/v1/example") };
```

Export the module manifest as `frontend/src/modules/example/manifest.tsx`:

```tsx
export default {
  id: "example",
  labelKey: "example.name",
  icon: <Box />,
  permission: "example.view",
  dependencies: [],
  render: (context) => lazyView(<ExamplePage t={context.t} />, context.t("status.loading")),
} satisfies FrontendModuleManifest;
```

The Vite manifest discovery loads it automatically; no central catalog edit is required. The launcher, desktop and taskbar use the registry metadata. Add locale keys and focused contract/component tests.
