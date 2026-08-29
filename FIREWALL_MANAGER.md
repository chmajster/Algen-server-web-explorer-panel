# Firewall Manager

## Purpose

Firewall Manager manages the firewall of the local Linux host. It is intentionally separate from DCST, which retains responsibility for logical segmentation and Proxmox Firewall reconciliation. Supported local backends are UFW, firewalld and nftables; the active backend is detected server-side.

## Architecture and safety

The frontend sends typed rule fields only. It never sends executables, shell fragments or configuration paths. FastAPI validates the models, enforces the shared session/RBAC/CSRF boundary and requires PAM re-authentication plus exact confirmation for mutations. Privileged firewall execution crosses the existing Unix-socket privileged broker through the dedicated `firewall` operation. The broker revalidates backend and argv shape and never uses `shell=True`.

Every mutation is executed as a WebNAS job with the sequence `validate -> plan/diff -> backup -> apply -> verify -> rollback on failure`. Changes that may affect SSH, the current WebNAS port, the current administrator source address, global firewall state or a blocking rule return a lockout warning and require explicit acknowledgement. nftables writes are limited to the dedicated `inet webnas` table; unrelated administrator nftables rules are read-only.

## UI

Sections: Overview, Rules, Open Ports, Backups and Activity. Open Ports correlates `ss` listeners with normalized firewall rules and shows process/service information when the kernel exposes it. The layout uses the shared WebNAS table/form conventions and responsive CSS for desktop, tablet and phone layouts.

## API

- `GET /api/modules/firewall-manager/status`
- `GET /api/modules/firewall-manager/rules`
- `GET /api/modules/firewall-manager/listening-ports`
- `POST /api/modules/firewall-manager/rules/plan`
- `POST /api/modules/firewall-manager/rules`
- `PUT /api/modules/firewall-manager/rules/{id}`
- `DELETE /api/modules/firewall-manager/rules/{id}`
- `POST /api/modules/firewall-manager/enable`
- `POST /api/modules/firewall-manager/disable`
- `POST /api/modules/firewall-manager/reload`
- `GET /api/modules/firewall-manager/export`
- `GET/POST /api/modules/firewall-manager/backups`
- `POST /api/modules/firewall-manager/backups/{id}/restore`
- `GET /api/modules/firewall-manager/activity`

## Permissions

`firewall.view`, `firewall.rules.create`, `firewall.rules.edit`, `firewall.rules.delete`, `firewall.enable`, `firewall.disable`, `firewall.reload`, `firewall.backup`, `firewall.restore`. Backend authorization is authoritative; hidden frontend controls are not a security boundary.

## Packages

APT: `ufw`, `nftables`, `iproute2`. DNF/YUM: `firewalld`, `nftables`, `iproute`. Module Center uses the existing apt/dnf/yum package executor.

## Limitations

Firewall Manager normalizes common UFW/firewalld/nftables rules. Arbitrary pre-existing nftables expressions remain visible but are intentionally not editable unless they belong to the WebNAS nftables table. Rule-level enable/disable is exposed only where the backend has a stable native representation; deletion/recreation is not presented as a fake enable toggle. Import/export uses the normalized WebNAS schema rather than accepting raw firewall scripts.

## Troubleshooting

If no backend is detected, install/enable one supported firewall through Module Center and refresh status. If a mutation fails, inspect the corresponding global WebNAS job and Activity Center event; the automatic pre-change backup ID is retained in the job result. A rollback failure is reported explicitly and never hidden.
