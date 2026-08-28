# Self-hosted GitHub Runner security

WebNAS uses GitHub-hosted runners for normal Pull Request CI. Long-lived self-hosted runners are reserved for trusted code after it reaches `main` or for an explicit manual run from `main`.

## Trust boundary

Pull Request code must run on `ubuntu-latest`. Do not add `pull_request_target` jobs that check out and execute code from an untrusted Pull Request. The self-hosted workflow must not have a `pull_request` trigger.

The expected flow is:

```text
Pull Request
  -> GitHub-hosted runner
     -> lint / typecheck / pytest / vitest / build / security checks
  -> merge
main
  -> self-hosted runner
     -> trusted integration checks
     -> optional protected deployment
```

## Runner account

Run the service as a dedicated account such as `github-runner`. The account should not share a home directory, SSH agent, credentials, or shell history with an administrator account.

Default restrictions:

- no access to `/root`;
- no private SSH keys belonging to other users;
- no global `sudo NOPASSWD: ALL`;
- no Proxmox tokens unless a specific trusted job requires them;
- no WebNAS application credentials;
- no production deployment credentials on a build-only runner;
- no Docker socket unless the job genuinely requires Docker daemon access.

Access to `/var/run/docker.sock` is effectively host-administration access in many configurations. A process that can control the Docker daemon can commonly mount host filesystems, start privileged containers, and obtain control of the runner host. Treat membership in the `docker` group as privileged access.

## Separate build and deployment runners

For a production setup, prefer separate runners:

```text
build-runner
- labels: self-hosted, linux, homelab
- no sudo
- no Docker socket unless required
- no production credentials

deploy-runner
- labels: self-hosted, linux, homelab, deploy
- trusted main only
- only required network access
- only required environment secrets
- narrowly scoped sudo rules when unavoidable
```

The repository workflow expects `self-hosted`, `linux`, and `homelab` labels for trusted integration work. The optional production deployment gate additionally expects `deploy`.

## GitHub permissions and secrets

Keep `GITHUB_TOKEN` permissions explicit and minimal. Normal CI and trusted integration use `contents: read`. Release publishing is the only workflow in this design that requires `contents: write`.

Do not hard-code tokens, passwords, API keys, private keys, or Proxmox credentials in workflow files. Store deployment secrets in the `production` GitHub Environment and expose only the secrets required by the deployment job.

## Production environment

Create a GitHub Environment named `production` and configure protection rules appropriate for the installation, for example required reviewers and deployment branch restrictions. The deployment job is intentionally manual and cannot start from a Pull Request event.

## Host hardening

Keep the runner OS patched and minimize installed software. Use a dedicated filesystem location for the runner workspace, restrict inbound network access, and allow outbound access only as required. Do not reuse the runner host as an administrator workstation.

Where possible, use ephemeral or disposable runners for higher-risk jobs. A long-lived runner should be considered persistent infrastructure: a compromised job can leave files, processes, credentials, or modified tooling behind for later jobs.

After a suspected compromise, stop the runner, rotate every credential reachable from it, discard or rebuild the host, and re-register the runner with a fresh token.
