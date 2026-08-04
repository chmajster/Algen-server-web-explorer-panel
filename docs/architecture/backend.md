# Backend

`app.main` is the ASGI entry point. `app.bootstrap.create_app()` is the composition root and accepts an optional typed `AppConfig` and `ModuleRegistry`. It configures middleware, exception mapping, lifecycle, manifest routers and static frontend mounting.

Authentication, platform health, File Manager and Transfer Center have separate HTTP adapters. The former mixed `http_api.py` router no longer exists. File and transfer endpoints are registered only through their manifests.

`app.core` is dependency-stable:

- `core.modules` validates manifests and performs dependency ordering;
- `core.errors` defines the `/api/v1` success/error envelope;
- `core.jobs` defines typed snapshots, steps and handler ports.

Module manifests contain import references, but importing occurs only after schema and dependency validation. Manifests are local, declarative YAML and are never downloaded or executed.

Cross-module imports target explicit `public.py` facades. The architecture test rejects imports of another module's models, repositories, services or adapters. System interactions remain behind existing allowlists and adapters. New domain/application code must not call subprocess, systemd, PAM, Docker or the filesystem directly; it declares a protocol and receives an adapter from the composition root.
