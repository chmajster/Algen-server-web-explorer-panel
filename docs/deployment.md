# Deployment

## Promotion path

Production promotion is intentionally separate from pull-request execution:

`PR -> hosted CI/CodeQL/dependency review -> merge main -> trusted integration -> GitHub Environment production approval -> blue/green deploy -> post-deploy smoke -> rollback on failure`.

Pull requests never execute the production deployment job.

## CI

`.github/workflows/ci.yml` validates version consistency, backend quality, backend unit/integration/security tests, frontend lint/type/test/build/OpenAPI/audit checks, Playwright E2E and shell syntax. CodeQL is maintained in a dedicated workflow.

Release tags run `.github/workflows/release.yml`, rebuild and test the tagged main revision and publish backend/frontend artifacts, checksums and SBOM files.

## Trusted runner

`.github/workflows/trusted-self-hosted.yml` runs only for `main` or an explicit workflow dispatch on `main`. The first job runs read-only host-level Linux/PAM/systemd tests and release/installer regression tests on a trusted self-hosted Linux runner.

The production job uses a runner with `self-hosted`, `linux` and `deploy` labels and GitHub Environment `production`. Configure required reviewers on that Environment to make approval mandatory. Repository/environment variables may override `WEBNAS_ROOT`, `WEBNAS_CONFIG` and `WEBNAS_SERVICE_USER`; defaults match the installer.

The workflow checks out the exact target revision, disables persisted Git credentials and verifies that the revision is reachable from `main` before deployment. Automatic promotion through `workflow_run` can proceed only after the `Automated tests` workflow succeeds. A manual `workflow_dispatch` with `deploy=true` performs an additional GitHub Actions API check and refuses deployment unless the exact `TARGET_SHA` has a successful `Automated tests` run triggered by a push to `main`. Manual trusted checks with `deploy=false` do not require this deployment gate.

## Existing blue/green mechanism

`scripts/deploy_from_checkout.sh` stages the approved checkout as `/opt/webnas/releases/github-<sha>`, creates an isolated Python virtualenv, runs `npm ci`, builds and verifies the frontend, then delegates activation to the existing `scripts/webnas_release.py` mechanism.

`webnas_release.py` owns:

- blue/green ports (`15101` and `15102`),
- inactive-slot selection,
- `WEBNAS_CANDIDATE` and `WEBNAS_SLOT`,
- candidate health validation,
- systemd slot services,
- atomic Nginx handover,
- the `current` symlink,
- persisted `deployment.json`,
- public health validation,
- drain/stop of the previous slot.

The CI/CD implementation does not introduce a second deployment topology.

## Health checks

Candidate activation keeps the compatibility `/api/health` check used by existing installer/release code. After public handover the trusted deployment additionally checks:

- `GET /api/health/live` — process liveness only;
- `GET /api/health/ready` — local application/module initialization readiness;
- `/` — frontend/gateway smoke test.

Liveness is not coupled to external Proxmox, Docker or other optional providers.

## Rollback

During handover `webnas_release.py` automatically restores the old slot if the public health check fails.

After a successful handover, `deployment.json` keeps `previous_slot`, `previous_port` and `previous_release`. If the additional post-deploy live/readiness/frontend smoke test fails, `scripts/deploy_from_checkout.sh` invokes `scripts/rollback_release.py`. The rollback helper:

1. starts and health-checks the previous slot;
2. atomically points Nginx and `current` back to the previous release;
3. updates the active-slot marker and deployment state;
4. stops/disables the failed slot;
5. validates public health again.

The workflow exits failed after a rollback so GitHub records that the attempted production promotion did not succeed.

## Concurrency and secrets

Production deployment uses a single concurrency group with cancellation disabled. Deployment has an explicit timeout. No secret value is echoed; the workflow uses environment variables only for non-secret paths/user configuration, while repository credentials are not persisted into the checkout. The trusted workflow has read-only `actions` permission solely to verify the prior CI result for a manual production deployment.
