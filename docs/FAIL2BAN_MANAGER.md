# Fail2Ban Manager

Fail2Ban Manager (`fail2ban-manager`) manages the local Fail2Ban installation on the WebNAS host without exposing a shell interface.

## Detection and dashboard

The backend detects `fail2ban-client`, `systemctl` and `journalctl` by absolute executable path. The dashboard reports:

- package/client availability;
- Fail2Ban version;
- systemd active/enabled state;
- daemon ping status;
- active jail count;
- currently banned IP count;
- cumulative bans reported by active jails.

A missing Fail2Ban installation is represented as an unavailable/degraded module state rather than an attempt to install packages implicitly.

## Jails and bans

The API exposes jail status and banned addresses. Jail names are restricted to a conservative `[A-Za-z0-9_.-]` grammar. IPv4 and IPv6 addresses are parsed and normalized with Python `ipaddress` before they reach `fail2ban-client`.

Supported actions include:

- manual ban;
- manual unban;
- enable/disable through a WebNAS-managed override;
- configuration update;
- daemon reload;
- service restart.

Ban and unban operations require explicit confirmation. The UI presents the target jail and address before execution.

## Command execution

The module never uses `shell=True`, `os.system`, `eval`, or client-provided command fragments. Every external command is executed with a fixed argument array, an absolute executable path, bounded timeout and controlled locale.

Representative commands are equivalent to:

```text
fail2ban-client status
fail2ban-client status <validated-jail>
fail2ban-client set <validated-jail> banip <validated-ip>
fail2ban-client set <validated-jail> unbanip <validated-ip>
fail2ban-client -t
fail2ban-client reload
systemctl restart fail2ban
```

## Managed configuration

Fail2Ban Manager does not rewrite package-owned `jail.conf` or arbitrary administrator files. WebNAS owns only:

`/etc/fail2ban/jail.d/webnas-<jail>.local`

Configuration writes follow this sequence:

1. validate jail name and every supported field;
2. render a complete managed override;
3. write a temporary file in the target directory;
4. flush and `fsync` the file;
5. atomically replace the managed override;
6. `fsync` the directory;
7. run `fail2ban-client -t`;
8. reload Fail2Ban;
9. restore the previous managed file and reload again if validation or reload fails.

Input values cannot contain control characters. The accepted configuration surface is intentionally limited to known jail properties such as filter, backend, port, maxretry, findtime, bantime and action.

## Logs

Logs are read through `journalctl -u fail2ban` with server-controlled arguments. The browser may provide filters such as text query, jail, validated IP, action (`ban`/`unban`) and result limit, but it cannot supply arbitrary journalctl arguments.

## Events

The module publishes through the existing WebNAS event bus:

- `fail2ban.ip_banned`
- `fail2ban.ip_unbanned`
- `fail2ban.jail_changed`
- `fail2ban.service_changed`

These events can be subscribed to by Webhook Manager.

## Audit

Mutating operations are recorded through the existing WebNAS activity/audit infrastructure. The recorded details contain safe metadata such as jail and normalized IP, never credentials or command strings supplied by a browser.

## API

Base path: `/api/modules/fail2ban-manager`.

Main endpoints:

- `GET /dashboard`
- `GET /jails`
- `GET /jails/{jail}`
- `GET /jails/{jail}/config`
- `PUT /jails/{jail}/config`
- `PUT /jails/{jail}/enabled`
- `GET /jails/{jail}/actions/plan`
- `POST /jails/{jail}/ban`
- `POST /jails/{jail}/unban`
- `POST /reload`
- `POST /restart`
- `GET /logs`

## RBAC

Permissions:

- `fail2ban-manager.view`
- `fail2ban-manager.manage`
- `fail2ban-manager.ban`
- `fail2ban-manager.unban`
- `fail2ban-manager.logs.view`
- `fail2ban-manager.configure`

Administrators receive all permissions. Operators receive operational actions and logs but not configuration authority. Auditors receive read/log access only.
