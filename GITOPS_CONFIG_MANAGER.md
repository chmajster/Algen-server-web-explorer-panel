# GitOps Config Manager

## Overview

GitOps Config Manager versions an explicit, non-secret subset of WebNAS configuration in a dedicated repository under `paths.data_dir/gitops-config`. It never commits the WebNAS installation directory or Secrets Manager storage.

## Export allowlist

The current allowlist contains:

```text
webnas/config.yaml
webnas/modules.json
```

`security.session_secret` is removed before export. Module export is metadata-only and explicitly excludes credentials and Secrets Manager data. `.env`, private-key, credential and secret patterns are ignored and a pre-commit secret scanner blocks commits when password/token/API-key/private-key patterns are detected. Findings expose only path, line and secret type; values are redacted.

## Git operations

Supported operations include init, local/remote configuration, status, branch selection, diff, history, commit, fetch, pull, push, restore and revert. Remote URLs are restricted to HTTPS or SSH. Passwords embedded in URLs and `file://` repositories are rejected. Git is always executed with argument arrays and `GIT_TERMINAL_PROMPT=0`; no operation uses `shell=True`.

Pull uses fetch plus `merge --ff-only`. Divergent history/conflicts are returned as a controlled GitOps conflict and are never silently overwritten. Restore is restricted to the export allowlist. Destructive `git reset --hard` is not used.

## Job Queue integration

Fetch, pull and push execute through the central Job Queue Manager with progress, bounded logs, timeout, audit and retry policy. Local commit/restore/revert remain synchronous bounded operations.

## API

```text
GET  /api/modules/gitops-config-manager/overview
GET  /api/modules/gitops-config-manager/changes
GET  /api/modules/gitops-config-manager/history
GET  /api/modules/gitops-config-manager/secret-scan
PUT  /api/modules/gitops-config-manager/repository
POST /api/modules/gitops-config-manager/commit
POST /api/modules/gitops-config-manager/sync/{fetch|pull|push}
POST /api/modules/gitops-config-manager/branch/checkout
POST /api/modules/gitops-config-manager/restore
POST /api/modules/gitops-config-manager/revert
```

## RBAC

- `gitops.view`
- `gitops.manage`
- `gitops.commit`
- `gitops.pull`
- `gitops.push`
- `gitops.rollback`

All mutations require CSRF; high-risk operations are audited.

## Authentication

Git credentials are not stored in Git remote URLs. Use the host SSH agent/key mechanism or a future explicit Secrets Manager credential bridge. The module intentionally refuses to persist plaintext passwords/tokens.
