# WebNAS architecture

WebNAS is a modular monolith: one FastAPI process, one React application and independently owned business modules. The composition root creates infrastructure and discovers module manifests; it does not know module implementation details.

```text
main.py -> bootstrap.create_app -> ModuleRegistry -> module public routers
                                      |
                                      +-> diagnostics and /api/v1/modules

React bootstrap -> frontend ModuleRegistry -> launcher / desktop / taskbar
                                      |
                                      +-> lazy feature components and API clients
```

The stable core contains contracts for modules, errors and long-running jobs. Business code may depend on these contracts. The core never imports business modules.

## Request flow

```text
HTTP -> middleware -> module API schema -> application service -> domain port -> infrastructure adapter
                                           |                    |
                                           +-> domain error     +-> filesystem/systemd/SQLite/subprocess
```

Every backend router is registered from a validated built-in manifest, so router composition follows the same path for every feature. Frontend manifests are discovered from module directories and own their lazy renderers and typed API clients.
