# Compliance Manager

Compliance Manager is the WebNAS host-compliance application for Linux policy assessment. It is intentionally read-only: a scan observes effective host configuration, produces evidence and remediation guidance, calculates a score, and writes scan activity to Activity Center. It does not silently modify SSH, sudo, PAM, sysctl, mount or firewall configuration.

## Scope

The initial profile is `cis-linux-level1`, presented as **CIS-aligned Linux Level 1**. The implementation maps selected automatable controls to common CIS Linux Level 1 guidance, but it is not an official CIS certification. Exact applicability and numbering differ between Debian, Ubuntu, RHEL-family, Fedora and Proxmox benchmarks.

Policy areas:

- SSH: root login, empty passwords, X11 forwarding and authentication retry limits.
- sudo: pseudo-terminal usage, dedicated logging and review of `NOPASSWD` grants.
- Filesystem: `/tmp` and `/dev/shm` hardening plus protected account-file ownership/modes.
- Kernel: effective ASLR, link-protection and IPv4 redirect sysctl values from `/proc/sys`.
- PAM: password-quality, failed-login lockout and password-hash policy discovery.
- Firewall: active backend and an explicit normalized ruleset through Firewall Manager.

Results use `pass`, `fail`, `manual`, `error` or `not_applicable`. The compliance score uses only automated `pass`/`fail` controls; manual-review and read-error controls are reported separately instead of being silently counted as failures.

## API

Read endpoints require `compliance.view`; scans require `compliance.scan`, CSRF through the normal mutating-user dependency, and run as a WebNAS job.

```text
GET  /api/modules/compliance-manager/summary
GET  /api/modules/compliance-manager/controls
GET  /api/modules/compliance-manager/controls?category=ssh
GET  /api/modules/compliance-manager/benchmarks
GET  /api/modules/compliance-manager/policies
POST /api/modules/compliance-manager/scan
```

`compliance.view` is granted to administrator, operator and auditor roles. `compliance.scan` is granted to administrator and operator roles. Scan start/completion events are recorded in Activity Center.

## Safety model

The scanner reads fixed operating-system paths and effective configuration only. `sshd -T` is executed as a fixed argument array with `shell=False`; other checks read fixed files such as `/proc/self/mounts`, `/proc/sys`, `/etc/sudoers`, selected PAM files and `/etc/login.defs`. Firewall state is consumed through the existing Firewall Manager provider. The browser cannot submit commands, paths, sysctl names or arbitrary benchmark code.
