# WebNAS Desktop Shell

## Scope

WebNAS Shell is the single orchestration boundary for desktop chrome and application lifecycle. Applications must use shell services instead of manipulating shell DOM, z-indexes, overlays or taskbar/start-menu state directly.

## Managers

- `LayerManager` — authoritative system layer ordering and CSS variables.
- `WindowManager` — window open/focus/minimize/maximize/close commands and current window snapshot.
- `TaskbarManager` — taskbar pinning, order and badges.
- `StartMenuManager` — launcher visibility, pinning and ordering.
- `ContextMenuManager` — single context menu request lifecycle; legacy `ContextMenu` calls are routed through it.
- `NotificationManager` — normalized notification history, read state and actions.
- `DesktopManager` — desktop selection, folder/shortcut creation commands, sorting, alignment and icon positions.
- `ClipboardManager` — shared copy/cut/paste state.
- `SearchManager` — registered global search providers with runtime permission predicates.
- `ActivityManager` — shell activity event contract.
- `ApplicationManager` — validated application manifests and lifecycle requests.
- `SessionManager` — lock/logout/restart/shutdown command contract.
- `DeviceManager` — desktop/tablet/mobile mode.

## Layer model

The layer order is controlled only by `LayerManager`:

1. desktop
2. windows
3. window-overlays
4. taskbar
5. start-menu
6. context-menu
7. notification-center
8. toast
9. modal
10. system-critical

CSS must use the installed `--webnas-layer-*` variables. Components must not create larger arbitrary z-index values. In particular, context menus are always above Start, removing the previous right-click-under-Start failure mode.

## Context menus

`WebNAS.contextMenu.open({ x, y, items })` is the public entry point. The single `SystemContextMenuHost` renders all requests. The host handles viewport clamping, outside-click close, Escape, keyboard navigation, disabled items, checked items, separators, dynamic children and mobile bottom-sheet presentation.

Legacy callers may temporarily render `<ContextMenu>`, but that component no longer renders a portal. It is a compatibility adapter that submits the request to `ContextMenuManager`.

## Application manifests

Shell manifests use this shape:

```json
{
  "id": "docker",
  "name": "Docker",
  "description": "Docker management",
  "version": "1.0.0",
  "entry": "/apps/docker",
  "permissions": ["docker.read", "docker.manage"],
  "multiWindow": true,
  "category": "system"
}
```

`ApplicationManager.validate()` rejects invalid IDs, traversal-style entries, malformed semantic versions and malformed permission identifiers. Installation and privileged lifecycle work must remain in the backend module/package-center boundary; the browser must never install arbitrary executable code.

## RBAC

Visibility is not authorization. Search results, context-menu actions and launcher entries may use permission predicates to hide unavailable actions, but every administrative operation must also be authorized by its backend endpoint. Existing module/app-store endpoints remain responsible for server-side permission checks and CSRF validation.

## User state

Persistent shell layout is stored per user through:

- `GET /api/shell/preferences`
- `PUT /api/shell/preferences`

The backend validates bounds and identifiers, writes atomically and stores state under the configured WebNAS data directory. `localStorage` is not the source of truth for shell layout.

The persisted model contains desktop metadata/entries, taskbar order, Start order/hidden items, recent files, windows, widgets, notification read metadata and mobile state.

## Window lifecycle

1. Caller requests `WebNAS.window.open()` or an existing desktop action opens an app.
2. The shell validates application availability/RBAC at the integration boundary.
3. `WindowManager` issues the managed state action.
4. The window reducer creates/focuses the window and assigns only a window-layer z-index.
5. Taskbar derives running/grouped state from window state.
6. Close removes the instance after dirty-state confirmation when required.
7. Persisted window geometry is restored through the shell preference model.

No application should directly raise its own z-index above shell chrome.

## Notifications

`WebNAS.notification.send()` accepts a source, level, category and optional actions. `NotificationManager` owns history/read state. Toasts are presentation of recent events; they are not the notification database.

Backend events for tasks, modules, services, containers, backups, security and updates should be normalized before display. Notification actions must call normal authorized backend APIs.

## Search

Providers register through `WebNAS.search.register(id, provider)`. Results have a category, keywords, action and optional permission predicate. Providers may represent applications, files, directories, services, containers, settings or administrative actions. Executing a result must still pass backend authorization for privileged operations.

## Mobile mode

At `<=640px` WebNAS uses a dedicated mobile shell:

- one visible application window fills the application workspace;
- resize/desktop drag affordances are disabled;
- Start becomes a full-screen launcher region above the mobile taskbar;
- notification/action/calendar panels become bottom sheets;
- context menus are rendered as bottom sheets;
- controls use touch-sized targets;
- safe-area insets and dynamic viewport units are honored;
- orientation changes update persisted mobile metadata without resetting application state.

Tablet mode covers `641–1024px`; desktop mode is above `1024px`.

## Adding a new application

1. Define the backend capability and RBAC permissions.
2. Register the backend router/module using the existing module framework.
3. Add a frontend manifest/registry entry with lazy renderer.
4. Register an `ApplicationManager` manifest with a safe internal entry path.
5. Register search/context-menu/notification integrations through shell APIs only.
6. Add regression tests for authorization, manifest validation, window lifecycle and mobile layout.

## Security rules

- Never render application/file/notification names using unsanitized HTML.
- Do not accept `javascript:` or arbitrary executable URL schemes for shortcuts.
- Normalize and validate filesystem paths on the backend using the existing path-policy layer.
- Validate CSRF for state-changing requests.
- Validate RBAC again on every administrative backend operation.
- Manifests cannot specify arbitrary filesystem entry points or browser script URLs.
- Apps do not own shell overlays, z-index or global DOM mutation.
