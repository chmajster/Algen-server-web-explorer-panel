# Privileged operation broker

WebNAS is moving host mutation out of the HTTP/FastAPI process. The privileged operation broker is the only component intended to retain UID 0 after the migration is complete.

## Trust boundary

The broker listens on `/run/webnas/privileged.sock`. The systemd socket is owned by `root:webnas` with mode `0660`. The broker does not authenticate requests with an API key stored in the web process. On Linux it reads `SO_PEERCRED` from the accepted Unix socket and requires the peer UID to match the configured WebNAS service account.

The request protocol is versioned JSON with a 1 MiB hard frame limit. The envelope contains a request id, audit actor, operation enum and operation payload. Unknown envelope fields and unknown operations are rejected.

## No generic root shell

There is intentionally no `shell`, `exec`, `command` or arbitrary executable operation. The policy layer rebuilds executable paths from a fixed `/usr/sbin:/usr/bin:/sbin:/bin` search path and launches subprocesses with `shell=False`.

Enabled operation families are:

- `systemd`: fixed actions and allowlisted WebNAS/application services; Proxmox and critical OS units are denied;
- `account`: a closed set of local account/group tools, with protected system/WebNAS identities denied;
- `ownership`: mkdir/chown only below approved WebNAS/user roots;
- `managed_file`: writes only to symbolic, compiled-in configuration targets for Samba and DHCP;
- `power`: only typed `poweroff` or `reboot`;
- `package`: package-manager operations with a fixed manager set, allowed subcommands, package-token validation and restricted package-file/source paths.

The protocol reserves `update_service` for the self-update migration, but the dispatcher currently rejects it. A reserved operation is not an enabled capability.

## Defense in depth

Authorization remains two-layered. HTTP handlers must continue to enforce session authentication, RBAC, CSRF and explicit destructive confirmations before requesting a broker operation. The broker then independently validates the host mutation and does not trust browser-derived executable paths, shell syntax, protected identities, arbitrary systemd units or arbitrary filesystem paths.

Broker logs contain request id, peer PID/UID, actor metadata, operation, result and exit code. Output is passed through centralized redaction. Passwords and other secret input must never be logged.

## Rollout

The broker service/socket can be introduced before FastAPI loses UID 0. This is deliberate: the web service is switched to the unprivileged `webnas` account only after all required package, service, mount/network, local-account and privileged-file call sites use this boundary and their integration tests pass.

The rollout is complete only when:

1. standard and blue/green FastAPI units use `User=webnas` and `NoNewPrivileges=true`;
2. required privileged mutations have no direct root-process fallback;
3. architecture/security tests reject new privileged subprocess/file mutations outside the broker and installer/release control plane;
4. trusted integration tests exercise broker-backed mutations on a disposable Linux host.
