# Changelog

## Unreleased

- Added and expanded Image Converter with server-directory and temporary-upload workflows, resizing, presets, metadata stripping, collision handling and conversion size statistics.
- Redesigned Image Converter UI around a clearer source → settings → result workflow, with improved directory browsing, upload dropzone, responsive controls, status cards and mobile layout.

## v0.1.33 — 2026-09-09

- Added the WebNAS shell foundation and desktop/runtime architecture.
- Unified RBAC with LDAP/AD group synchronization, policies and scoped authorization, including compatibility and security hardening.
- Routed Docker Engine access through the privileged broker and fixed the Settings policy observer freeze.
- Added API Explorer with typed frontend integration, read-only OpenAPI diagnostics and structural contract tests, including reusable parameter references and network-isolation coverage.

## v0.1.32 — 2026-08-31

- Expanded Proxmox Manager with advanced cluster, capacity, placement, storage, backup, replication, HA, migration, network, SDN, cloud-init, policy and orphan-management workflows, plus the matching frontend and operational documentation.
- Refined authentication UX with explicit PAM/LDAP provider selection and strengthened LDAP attribute normalization and connection handling.
- Hardened installer update/reinstall flows and their CI coverage, including full-reinstall/menu scenarios and correct preservation of installer exit statuses.
- Improved frontend build observability with context-neutral build completion output, explicit bundle-validation stages and JavaScript asset progress reporting.


## v0.1.31 — 2026-08-30

- Separated LDAP Authentication in Settings from the independently installable LDAP Manager, including independent configuration databases and Secrets Manager credentials.
- Added multi-server LDAP authentication failover, immutable directory identities, LDAP group-to-WebNAS RBAC mapping, access policies, diagnostics, session policy refresh, and explicit Local/PAM/LDAP provider selection without cross-provider password fallback.
- Added LDAP Manager support for multiple LDAP/Active Directory/FreeIPA connections, directory browsing, users, groups, OUs, schema, paged search/export, bulk operations, provider-aware password controls, granular RBAC, audit logging, and injection/TLS/SSRF protections.
- Hardened PAM to use only `/etc/pam.d/webnas`, added installer/upgrade migration validation and real OpenLDAP CI coverage, and fixed legacy session migration, object-scope authorization, paging, and TLS compatibility regressions found during review.

## v0.1.30 — 2026-08-30

- Expanded Storage Manager with complete read-only diagnostics and brokered advanced probes.
- Added application-owned Local database authentication as the default, optional PAM/LDAP system authentication, provider-aware sessions, local user administration, POSIX companion mappings, LDAP security controls, and installer bootstrap support.
- Hardened release/update activation so release helpers reliably re-exec inside the candidate virtualenv, including symlinked Python launchers, and added an HTTP-safe clipboard fallback for copying update error details.
- Added Firewall Manager, Security Center and Network Tools with granular RBAC/audit, typed privileged firewall operations, serialized backup/apply/verify/rollback transactions, normalized UFW/firewalld/nftables handling, non-destructive posture scanning, and bounded network diagnostics.
- Added central Job Queue Manager, NTP Manager, Routing Manager, Login History and GitOps Config Manager with privileged-broker integration, safe routing transactions/rollback, authentication-event correlation, secret-safe GitOps workflows, frontend applications, generated OpenAPI contracts and regression coverage.
- Hardened infrastructure manager error boundaries and Job Queue lifecycle: unexpected NTP/routing failures no longer expose exception details, and permanent queue workers are explicitly managed daemon threads so unit/integration processes shut down deterministically.
- Refreshed supported backend/frontend dependencies and kept generated dependency metadata synchronized with the project source of truth.

## v0.1.29 — 2026-08-30

- Added Offline Repository Manager to `os-repositories`: Full/Selected/Delta `.tar.zst` bundles, dependency closure, controlled staging and hardened verification/import, durable offline jobs with SSE/retry/cancel, Air-Gapped Mode enforcement, granular offline RBAC, Hosts Manager group target generation, storage/retention/pinning/freeze/diagnostics, a complete React workflow, generated OpenAPI updates, tests, and operational documentation.

## v0.1.28 — 2026-08-30

- Expanded Proxmox Manager with live node/storage/cluster/VM detail views, central UPID task tracking, snapshots, cloning, migration, hardware and disk growth operations, full locked/backoff inventory auto-sync, a split responsive frontend, create-VM workflow, Host Registry identity preservation, audit integration, tests, and updated documentation without persisting Proxmox secrets or a duplicate VM/LXC inventory.

## v0.1.24 — 2026-08-29

- Added real browser-to-FastAPI E2E coverage and hardened appliance backup/restore validation and recovery workflows.
- Added native Alert Manager and safe read-only Storage Manager, and completed the typed privileged-operation broker so FastAPI can run unprivileged while privileged host mutations remain controlled.
- Reduced idle runtime work with lazy process enumeration, session-resolution caching, gzip compression, request deduplication, shared visibility handling, and event-driven task, job, update, mount, and network-transaction refresh with polling only as fallback.
- Improved runtime resilience with watchdog recovery, blue/green service detection, application-log source handling and filtering of unavailable legacy WebNAS systemd units.
- Reduced frontend startup cost through lazy feature/module boundaries and bundle budgets, and improved desktop UX with taskbar-safe dialogs plus horizontal Resource Monitor navigation.
- Improved Proxmox endpoint handling with scheme-less input and automatic API protocol detection, and expanded localized CSRF diagnostics.
- Added ordered multi-server DNS management with dedicated inputs, deduplication and `systemd-resolved` global DNS discovery.
- Prevented durable JobService records from remaining permanently `queued` after a process restart by recovering interrupted queued work into an explicit failed/retryable state.
- Refreshed supported backend/frontend dependencies and kept generated dependency metadata synchronized with the project source of truth.

## v0.1.23 — 2026-08-29

- Hardened hosted/trusted CI and production deployment so manual production promotion requires a successful hosted test run for the exact `main` revision; authentication diagnostics and baseline HTTP security headers were also strengthened.
- Consolidated persistent jobs, logs, plugins and the application/module-store architecture, and moved Credentials into a standalone application while preserving centralized secret handling and module integrations.
- Improved runtime resilience with watchdog recovery, blue/green service detection, application-log source handling and filtering of unavailable legacy WebNAS systemd units.
- Reduced frontend startup cost through lazy feature/module boundaries and bundle budgets, and improved desktop UX with taskbar-safe dialogs plus horizontal Resource Monitor navigation.
- Improved Proxmox endpoint handling with scheme-less input and automatic API protocol detection, and expanded localized CSRF diagnostics.
- Added ordered multi-server DNS management with dedicated inputs, deduplication and `systemd-resolved` global DNS discovery.
- Prevented durable JobService records from remaining permanently `queued` after a process restart by recovering interrupted queued work into an explicit failed/retryable state.
- Refreshed supported backend/frontend dependencies and kept generated dependency metadata synchronized with the project source of truth.

## v0.1.22 — 2026-08-28
- Reworked the DCST network-security control plane and hardened bulk blocking, live deletion warnings, preview concurrency, inventory permissions, policy-sync timestamps, and raw firewall-log filtering.

- Finished the application UI consistency layer across resource monitoring, settings, activity and transfer centers, network resources, Docker details, and Hosts Manager controls, with container-responsive regression coverage.

- Replaced blocking shared confirmations and prompts with non-blocking, minimizable desktop dialogs; preserved drafts across minimization, isolated concurrent dialogs, cancelled queued actions on logout, suspended hidden legacy-dialog keyboard handlers, and coalesced duplicate privileged Ansible operations.

- Added complete **DHCP Manager** with Kea DHCPv4/ISC detection, Package Center lifecycle, typed subnet/pool/reservation/lease management, configuration preview and native validation, atomic apply with verified backup/rollback, utilization/diagnostics/logs/service controls, granular RBAC/PAM/CSRF/audit, Proxmox Safe Mode, shared Hosts Manager identity and optional Pi-hole/AdGuard DNS synchronization.

- Added native **Proxmox Manager** with Proxmox VE API connections, shared Hosts Manager identity, centralized `proxmox_api` credentials, VM/LXC synchronization, live-node power actions, and direct reuse of the same `host_id` by Hosts Manager and Ansible Automation Controller.

- Added managed Proxmox VM/CT metadata tags for project, environment, location, resource type and Host Registry tags, while preserving administrator-created Proxmox tags and reporting permission/tag-policy failures without blocking host synchronization.

- Added a disposable `--portable` installer mode that runs WebNAS without installing it as a system service and keeps its isolated runtime below the launch directory.

- Fixed portable mode to consistently use `./portable-run/` for source, runtime, configuration, and cleanup, preserving compatibility when launched from an existing repository checkout.