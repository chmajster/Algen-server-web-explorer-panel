<div align="center">

# WebNAS

**A modern web-based administration panel for managing Linux servers, files, services, and infrastructure.**

FastAPI · React · TypeScript · PAM · systemd · rsync

[Installation](#installation) · [Features](#key-features) · [Modules](#modules) · [Documentation](#documentation)

</div>

---

## About

**WebNAS** provides a clean browser-based interface for managing a Linux server, inspired by modern desktop environments and NAS administration platforms.

It combines file management, system administration, user management, containers, networking, logs, automation, and infrastructure modules in a single interface.

Main project goals:

- authentication with local Linux accounts through PAM,
- no separate user password database,
- modular architecture,
- granular RBAC permissions,
- controlled administrative operations,
- responsive desktop and mobile interface,
- simple installation and updates through a single installer.

## Screenshots

### Dashboard

![WebNAS dashboard](docs/screenshots/webnas-dashboard.webp)

### Package Center

![WebNAS Package Center](docs/screenshots/webnas-package-center.webp)

### Settings

![WebNAS settings](docs/screenshots/webnas-settings.webp)

## Key Features

| Area | Capabilities |
|---|---|
| **File Manager** | Browse files, upload, edit, copy and move with `rsync`, monitor transfer progress |
| **Desktop UI** | Application windows, taskbar, Start menu, shortcuts, themes, wallpapers and per-user personalization |
| **Users & Groups** | Manage local Linux users, groups, roles and granular permissions |
| **Networking** | Interfaces, VLANs, bridges, bonds, DNS, routing, diagnostics and controlled network changes |
| **Network Resources** | SMB/CIFS, NFS, SSHFS and WebDAV integrated with File Manager |
| **DCST** | Logical `APMID.ENV` segmentation, reusable Ports/IPSets/Services, Proxmox Firewall reconciliation, block/unblock, drift detection and firewall diagnostics |
| **Containers** | Docker Engine, images, containers, Compose, networks, volumes, registries, backups and diagnostics |
| **Package Center** | Install and manage WebNAS modules |
| **Logs** | System logs, `journalctl`, kernel, services and Docker container logs |
| **Activity Center** | History of sign-ins, administrative changes, file operations and module jobs |
| **USB** | Automatic detection and mounting of supported USB storage devices |
| **Hosts Manager** | Central host inventory, SSH connections, repositories and power profiles |
| **Automation** | Ansible Automation Controller, schedules and Cron Manager |
| **DHCP** | Kea DHCPv4 / ISC DHCP subnets, pools, reservations, leases, diagnostics and transactional configuration |

## Modules

WebNAS includes a modular **Package Center** that allows infrastructure features to be added without expanding the core application.

Available and supported modules include:

- Samba
- Ansible Automation Controller
- Docker / Containers Manager
- Linux Updates
- DATA Communication & Segmentation Tool - DCST
- Proxmox Manager
- Nginx
- Squid Proxy
- Syncthing
- PostgreSQL
- MariaDB
- Redis
- central APT/RPM repositories
- Cron Manager
- DHCP Manager (Kea DHCPv4 / ISC DHCP)

Containerized applications can also be deployed through **Containers Manager**, including:

- Home Assistant
- Pi-hole
- AdGuard Home
- Uptime Kuma
- Jellyfin
- Nextcloud
- Nginx Proxy Manager

## Installation

### Requirements

- Linux with `systemd`
- `root` or `sudo` access
- Python **3.14**
- Node.js + npm
- `rsync`
- supported package manager: `apt`, `dnf` or `yum`

WebNAS is designed for systems including Debian, Ubuntu, Raspberry Pi OS, Fedora and RHEL-based distributions.

### Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

After installation, WebNAS is available by default at:

```text
http://SERVER_IP:5000
```

Sign in using a local Linux account.

### Custom Port

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --port 8080
```

### Update

Run the installer again:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

The installer detects an existing WebNAS installation and performs the supported update procedure.

Full installation documentation: [INSTALL.md](INSTALL.md)

## Architecture

```text
Browser
   │
   ▼
React + TypeScript
   │
   ▼
FastAPI
   │
   ├── PAM / Linux users
   ├── File operations / rsync
   ├── systemd
   ├── Docker
   ├── Network management
   ├── Package Center
   └── WebNAS modules
```

Core technology stack:

- **Backend:** Python 3.14 + FastAPI
- **Frontend:** React + TypeScript + Vite
- **Authentication:** PAM
- **Authorization:** RBAC
- **Service management:** systemd
- **File transfers:** rsync
- **Application/module state:** configuration files and SQLite depending on the component

## Security

WebNAS uses local Linux accounts as the primary identity source.

The project includes:

- PAM authentication,
- granular RBAC permissions,
- CSRF protection for state-changing operations,
- path and operation validation,
- secret redaction in logs,
- user and administrator activity auditing,
- controlled high-risk operations,
- automatic rollback for selected network changes,
- **Proxmox Safe Mode** when a Proxmox VE host is detected.

> [!IMPORTANT]
> For production deployments on Proxmox VE, running WebNAS inside a VM or LXC container is recommended instead of installing it directly on the hypervisor host.

## Documentation

Detailed documentation is available in separate files:

| Document | Description |
|---|---|
| [INSTALL.md](INSTALL.md) | Installation, updates, configuration and troubleshooting |
| [HOSTS_MANAGER.md](HOSTS_MANAGER.md) | Hosts Manager |
| [ANSIBLE_CONTROLLER.md](ANSIBLE_CONTROLLER.md) | Ansible Automation Controller |
| [CONTAINERS_MANAGER.md](CONTAINERS_MANAGER.md) | Docker and Containers Manager |
| [CRON_MANAGER.md](CRON_MANAGER.md) | Cron Manager |
| [DHCP_MANAGER.md](DHCP_MANAGER.md) | DHCP Manager: Kea/ISC, subnets, reservations, leases and safe configuration lifecycle |
| [DCST.md](DCST.md) | DCST architecture, Proxmox Firewall integration, Services, Ports, IPSets, TAGS, drift detection and troubleshooting |
| [PACKAGE_CENTER.md](PACKAGE_CENTER.md) | Package Center |
| [MODULES.md](MODULES.md) | Module architecture |
| [INFRASTRUCTURE_MODULES.md](INFRASTRUCTURE_MODULES.md) | Infrastructure modules |
| [IDENTITY.md](IDENTITY.md) | Users, roles and permissions |
| [APMID.md](APMID.md) | Application ownership and resource registry |
| [OS_REPOSITORIES.md](OS_REPOSITORIES.md) | Central APT/RPM repositories |
| [CHANGELOG.md](CHANGELOG.md) | Project changelog |

## Useful Commands

Check service status:

```bash
sudo systemctl status webnas
```

Restart WebNAS:

```bash
sudo systemctl restart webnas
```

Follow logs:

```bash
sudo journalctl -u webnas -f
```

## Repository

```bash
git clone https://github.com/chmajster/Algen-server-web-explorer-panel.git
cd Algen-server-web-explorer-panel
```

---

<div align="center">

**WebNAS — one interface for managing your Linux server.**

</div>
