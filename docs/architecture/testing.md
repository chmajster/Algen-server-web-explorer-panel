# Testing

Backend quality gates are Ruff, mypy, pytest and Bandit. `test_module_registry.py` covers manifest validation, ordering, duplicates, cycles, diagnostics and application factory isolation. `test_architecture_boundaries.py` ensures the composition root stays thin, the core cannot import business modules, cross-module imports use public facades, mixed routers stay removed, frontend clients stay composed and manifests remain non-executable data.

Frontend gates are TypeScript, ESLint, Vitest and the production build. Registry tests cover duplicate ids, dependencies and permission resolution. Transport tests cover typed JSON and the common error contract.

Adapters must be tested with fakes. Tests must not install packages, mutate systemd, create host users or alter host networking.
