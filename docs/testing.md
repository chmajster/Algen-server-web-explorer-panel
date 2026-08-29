# Testing

WebNAS separates fast unit tests, controlled integration tests, browser E2E tests and trusted host-level system tests.

## Backend

Unit tests are the default pytest layer:

```bash
python -m pytest -ra -m "not integration and not system"
```

Controlled integration tests run on GitHub-hosted Ubuntu and must not require a real Proxmox, Docker daemon, PAM login or production filesystem:

```bash
python -m pytest -ra -m integration
```

External systems should use fake adapters, fixtures or mock servers. Integration tests are marked with `@pytest.mark.integration`.

Host-level tests are marked `@pytest.mark.system`. They run only in `trusted-self-hosted.yml` on a trusted Linux runner. They may verify real Linux/PAM/systemd prerequisites, but should remain non-destructive unless a dedicated disposable environment is explicitly provided.

## Frontend unit/integration

From `frontend/`:

```bash
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Vitest covers components, hooks and integration boundaries. Design System tests cover table states, selection/actions, form semantics, modal/drawer keyboard behavior and confirmations.

## OpenAPI contract

Generate the committed TypeScript contract with:

```bash
npm run api:generate
```

Check that the committed contract matches FastAPI without modifying it:

```bash
npm run api:check
```

The exporter uses an isolated temporary runtime config and must not write to `/var/lib/webnas` or another production location.

## Playwright E2E

Install the browser once after `npm ci`:

```bash
npx playwright install chromium
```

Run the controlled browser-side mock suite locally:

```bash
npm run test:e2e
```

CI uses:

```bash
npm run test:e2e:ci
```

The checked-in mock E2E suite never points destructive File Manager, DCST or Package Center operations at production services. Critical flows cover authentication/session behavior, Desktop windows, File Manager administrative actions, DCST object/service workflows and Package Center installation flow.

A second Playwright profile exercises the actual browser -> Vite proxy -> FastAPI -> SQLite path:

```bash
npm run test:e2e:real
```

`playwright.real.config.ts` starts `backend/tests/e2e_real_server.py` with a temporary configuration and data directory. The test server replaces only PAM authentication and permission resolution inside that isolated test process; production application modules and routes remain unchanged. The real-stack suite verifies rejected and successful login, persistent cookie-backed session resolution, CSRF enforcement, logout, session expiry, request validation and Hosts Manager create/list/update/delete operations against the real backend repository. It is run for pull requests and `main` by `.github/workflows/real-e2e.yml`.

## Security checks

Backend runtime dependencies:

```bash
python -m pip_audit -r backend/requirements.txt
```

Frontend High/Critical gate:

```bash
npm audit --audit-level=high
```

CI also runs Ruff, mypy, Bandit, ESLint, TypeScript, CodeQL, architecture-boundary tests and shell syntax validation.
