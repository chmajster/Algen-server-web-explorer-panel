# Module contracts

A backend manifest declares `id`, name, version, category, icon, permissions, router references, dependencies, capabilities, system capabilities and menu entries. `ModuleRegistry` rejects invalid ids, duplicate registrations and cycles, then installs routers in topological order.

States are:

- `active` — registered and available;
- `disabled` — intentionally excluded;
- `unavailable` — a dependency is missing;
- `broken` — validation or initialization failed.

Modules communicate through public protocols, DTOs and `public.py` facades. A dependency must be declared in the consumer manifest. Importing another module's repository, persistence implementation or private service is prohibited and checked in CI. Cross-module notifications should use typed domain events rather than direct storage access.

The Package Center catalog and application features are exposed through the same runtime registry. Package manifests continue to describe installable system packages; built-in application manifests describe WebNAS routing and navigation capabilities.
