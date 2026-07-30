# Hosts Manager Linux agent

The Hosts Manager agent is a dependency-free Python 3 client that registers a Linux server, sends heartbeats and periodically reports sanitized system inventory to WebNAS. It connects outbound over HTTPS; no inbound agent port or firewall rule is required.

## Supported systems

- Debian, Ubuntu, Raspberry Pi OS and Proxmox
- Fedora, RHEL, Rocky Linux, AlmaLinux and CentOS
- openSUSE and SLES
- Arch Linux and Manjaro
- Alpine Linux

The installer requires `curl`, `python3`, `ip`, `hostname` and a trusted HTTPS certificate for the WebNAS endpoint. It uses systemd when available, OpenRC on Alpine and a cron/nohup fallback on other systems.

## Recommended installation

1. In Hosts Manager open **Installer**.
2. Choose the required active environment and APMID, then select a hostname pattern. The server derives the managed `<APMID>.<ENVIRONMENT>` group; it cannot be replaced from the browser.
3. Generate a short-lived one-time token. It requires a lifetime from 1 to 525600 minutes. Use a permanent token only for controlled fleet provisioning and bind it to a private IP where possible; permanent tokens have no expiry field and are stored with `expires_at = 0`.
4. Copy the generated command and run it as root on the target host.
5. Approve the new host and independently verify its SSH fingerprint.

The generated script does not ask for an SSH user, SSH port or SSH credential. Agent registration is outbound HTTPS and assigns the host to the chosen environment, the server-derived APMID group and any additional manual groups. SSH settings remain available for the separate SSH installation workflow. The generated script changes the hostname only when that option is enabled. Before registration it keeps the previous hostname in the enrollment metadata. It installs:

| Path | Purpose | Mode |
|---|---|---|
| `/opt/hosts-manager-agent/agent.py` | Agent executable | `0755` |
| `/etc/hosts-manager-agent/config.yaml` | Connection and interval settings | `0600` |
| `/var/lib/hosts-manager-agent/state.json` | Agent ID and authentication token | `0600` |
| `/var/log/hosts-manager-agent/agent.log` | Rotating runtime log | service-owned |
| `/etc/systemd/system/hosts-manager-agent.service` | systemd unit, when supported | standard unit |

`config.yaml` contains JSON, which is a valid YAML 1.2 subset. This avoids a runtime dependency on a YAML parser.

For automation, the bundled wrapper accepts values as arguments or environment variables:

```bash
sudo ./agent_install.sh \
  --server-url https://webnas.example.com \
  --token 'ONE_TIME_TOKEN'
```

Equivalent environment variables are `HOSTS_MANAGER_URL` and `HOSTS_MANAGER_TOKEN`. Avoid placing long-lived tokens in shell history.

## Configuration

```json
{
  "server": {
    "url": "https://webnas.example.com",
    "timeout_seconds": 15,
    "verify_tls": true
  },
  "agent": {
    "heartbeat_interval": 30,
    "report_interval": 300,
    "max_retries": 10
  },
  "authentication": {},
  "logging": {
    "level": "INFO",
    "file": "/var/log/hosts-manager-agent/agent.log"
  }
}
```

Do not disable TLS verification in production. The enrollment token is removed from configuration after successful registration. The server-issued agent token remains only in the private state file and is stored server-side as a salted hash.

## Commands

```bash
python3 /opt/hosts-manager-agent/agent.py version
python3 /opt/hosts-manager-agent/agent.py once
python3 /opt/hosts-manager-agent/agent.py heartbeat
python3 /opt/hosts-manager-agent/agent.py report
systemctl status hosts-manager-agent.service
journalctl -u hosts-manager-agent.service -n 100
```

`once` performs one heartbeat/report cycle and is useful after changing configuration. The agent retries transient network errors with bounded exponential backoff. Its file log rotates at 5 MiB and retains four archives.

## Report contents

The report contains bounded data in four sections:

- `basic`: hostname, FQDN, distribution, version, architecture, kernel, uptime and non-loopback addresses;
- `hardware`: DMI vendor/model/serial/UUID, CPU details, memory, block devices and filesystems;
- `system`: resource usage, interfaces, routes, DNS and service states;
- `packages`: detected package manager, installed package count, repository metadata and available/security update counts.

The API rejects reports larger than 2 MiB and recursively rejects keys that look like passwords, secrets, private keys or tokens.

## Identity lifecycle

Every installation has a stable installation ID and a server-issued agent ID. Pairing creates a random per-host salt and token hash. **Generate new identity** invalidates the current salt and returns a new raw token once. **Invalidate identity** removes authentication immediately and changes the host to `authentication_required`; reinstall or pair it again to restore communication.

Permanent enrollment tokens are reusable until revoked and therefore carry more risk. Their use count, reported hostnames, APMID, environment and managed group are audited. Prefer one-time tokens for individual hosts.

## Removal

Run the bundled removal script as root:

```bash
sudo ./agent_uninstall.sh
```

It stops the systemd/OpenRC service and removes only the agent-owned paths listed above. Afterwards invalidate the host identity in Hosts Manager. Removing the local files does not delete the server-side host or audit history.

## API authentication

The public control-plane endpoints are deliberately narrow:

- `GET /api/modules/hosts-manager/enrollment-script` — enrollment Bearer token;
- `POST /api/modules/hosts-manager/enroll` — enrollment Bearer token;
- `POST /api/modules/hosts-manager/agent/heartbeat` — agent Bearer token;
- `POST /api/modules/hosts-manager/agent/report` — agent Bearer token;
- `GET /api/modules/hosts-manager/agent/source` — public agent source, contains no secrets.

Administrative host, identity and audit endpoints still require an authenticated WebNAS session, CSRF protection for mutations and the matching Hosts Manager permission.
