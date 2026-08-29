# Security Center

## Purpose

Security Center is an advisory aggregation layer for WebNAS and the local host. It calculates a Security Score from 0 to 100 and presents actionable findings without applying automatic remediation.

## Data sources

The scan reuses Firewall Manager for firewall/open-port state, Linux Updates for package/security-update state, WebNAS HTTPS transport settings, SSH effective configuration, NSS/local account data, configuration-file permissions and bounded systemd journal inspection for failed authentication events. It does not create replacement user, networking, update, package, job or audit registries. Only finding acknowledgement/resolution state is persisted in `security-center.sqlite3`.

## Findings and score

Severities are Critical, High, Medium, Low, Info and Passed. Findings contain severity, title, description, affected resource, detection source, recommendation, timestamp, category and status (`open`, `acknowledged`, `resolved`). Score penalties are severity-weighted and clamped to 0-100. Area summaries cover firewall, authentication/SSH, updates, network exposure, TLS/HTTPS, users, permissions and system security.

Implemented checks include disabled/no-rule firewall state, permissive SSH root/password/empty-password settings, security/package updates and reboot requirement, public listeners without an explicit firewall match, WebNAS without HTTPS, multiple UID 0 accounts, unsafe WebNAS configuration write permissions and elevated failed-login volume. Unavailable data sources degrade to informational findings instead of silently reporting success.

## Scan flow

`POST /api/modules/security-center/scan` creates a standard WebNAS Job. Scan start/completion and finding state changes are written to Activity Center. Security Center never performs fixes as a side effect of scanning. Remediation remains a separate administrator workflow in the owning module.

## API

- `GET /api/modules/security-center/summary`
- `GET /api/modules/security-center/findings`
- `POST /api/modules/security-center/scan`
- `POST /api/modules/security-center/findings/{id}/state`
- `GET /api/modules/security-center/checks`

## Permissions

`security.view`, `security.scan`, `security.findings.manage`.

## UI

Sections: Overview, Findings, Authentication, Network, Updates, Certificates and Audit. The dashboard displays score, severity totals, area scores and scan age; filtered views reuse the same authoritative finding set.

## Limitations

The initial scanner is deliberately non-destructive and focuses on local-host/WebNAS posture. Distribution-specific MAC frameworks, kernel-hardening policies and advanced certificate-chain policy can be added as independent checks later without changing the finding contract. A finding marked resolved is administrative state; a new scan still detects the underlying condition and keeps the detection evidence current.

## Troubleshooting

If a source is unavailable, verify the owning WebNAS module/tool first (Firewall Manager, Linux Updates, `sshd`, `journalctl`, HTTPS settings). Scan jobs and redacted failures are available in the shared Jobs/Activity surfaces.
