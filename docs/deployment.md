# Deployment

## Promotion path

Production promotion is intentionally separate from pull-request execution:

`PR -> hosted CI/CodeQL/dependency review -> merge main -> trusted integration -> download exact hosted-CI frontend + Python wheelhouse artifacts -> GitHub Environment production approval -> blue/green deploy -> post-deploy smoke -> rollback on failure`.

Pull requests never execute the production deployment job.

## CI

`.github/workflows/ci.yml` validates version consistency, backend quality, backend unit/integration/security tests, frontend lint/type/test/build/OpenAPI/audit checks, Playwright E2E and shell syntax. CodeQL is maintained in a dedicated workflow.

The frontend job verifies `frontend/dist`, writes its SHA-256 asset manifest and stamps `.webnas-source-sha` with the exact `GITHUB_SHA` before uploading the immutable `frontend-dist` Actions artifact. Hidden integrity/provenance files are included in the artifact.

Backend quality also builds `python-wheelhouse` for the exact CI revision. The wheelhouse contains resolved runtime wheels, `.webnas-source-sha` and `.webnas-wheelhouse.sha256`. CI proves the artifact can install `backend/requirements.txt` into a clean virtualenv using `pip --no-index --find-links`, so deployment does not depend on package-index availability or newly resolved dependency bytes. Because this stage reads the canonical runtime requirements on every run, runtime dependency additions and upgrades are included in the same provenance/checksum gate before promotion.

Release tags run `.github/workflows/release.yml`, rebuild and test the tagged main revision and publish backend/frontend artifacts, checksums and SBOM files.

## Trusted runner

`.github/workflows/trusted-self-hosted.yml` runs only for `main` or an explicit workflow dispatch on `main`. The first job runs read-only host-level Linux/PAM/systemd tests and release/installer regression tests on a trusted self-hosted Linux runner.

The production job uses a runner with `self-hosted`, `linux` and `deploy` labels and GitHub Environment `production`. Configure required reviewers on that Environment to make approval mandatory. Repository/environment variables may override `WEBNAS_ROOT`, `WEBNAS_CONFIG` and `WEBNAS_SERVICE_USER`; defaults match the installer.

The workflow checks out the exact target revision, disables persisted Git credentials and verifies that the revision is reachable from `main` before deployment. Automatic promotion through `workflow_run` can proceed only after the `Automated tests` workflow succeeds. A manual `workflow_dispatch` with `deploy=true` resolves the successful hosted `Automated tests` run for the exact `TARGET_SHA` and refuses deployment if no successful push-to-`main` run exists. Manual trusted checks with `deploy=false` do not require this deployment gate.

The resolved CI run id is passed to the production job. Production downloads both `frontend-dist` and `python-wheelhouse` from that exact run using read-only Actions permission. It requires `.webnas-source-sha == TARGET_SHA` for both artifacts, validates the frontend asset manifest, runs `sha256sum --check` over the wheelhouse and records both manifest digests in the deployment summary. An artifact produced for another commit cannot be promoted.

## Existing blue/green mechanism

`scripts/deploy_from_checkout.sh` stages the approved checkout as `/opt/webnas/releases/github-<sha>`, requires tested frontend and Python wheelhouse artifacts for the same SHA, copies the frontend into the release without running `npm ci` or `npm run build`, creates the isolated Python virtualenv and installs runtime dependencies exclusively from the verified wheelhouse with `pip --no-index --find-links`. It then delegates activation to the existing `scripts/webnas_release.py` mechanism.

The deployment script revalidates the frontend integrity manifest and Python wheel checksums before activation. It records the hosted artifact manifest digests in `.webnas-frontend-manifest-sha256` and `.webnas-python-wheelhouse-manifest-sha256`. During handover WebNAS may add immutable hashed assets from the previous release so already-open browser sessions can finish lazy chunk requests; the active `index.html` and every file tracked by the hosted-CI manifest remain byte-for-byte verified.

The production runner no longer executes an npm build or resolves/downloads Python runtime dependencies from PyPI. The only release-local construction is the virtualenv itself; application source is the exact tested Git revision and installed dependency wheels are the exact hosted-CI artifact bytes.

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

Production deployment uses a single concurrency group with cancellation disabled. Deployment has an explicit timeout. No secret value is echoed; the workflow uses environment variables only for non-secret paths/user configuration, while repository credentials are not persisted into the checkout. The trusted workflow has read-only `actions` permission to resolve and download the successful hosted-CI artifacts for the exact approved revision.
