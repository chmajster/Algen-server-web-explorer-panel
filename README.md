<div align="center">

# WebNAS

**Modern web-based administration panel for Linux servers, files, services and infrastructure.**

FastAPI · React · TypeScript · Local users · PAM · LDAP · systemd · rsync

[Installation](#installation) · [Repository layout](#installer-layout) · [Documentation](#documentation)

</div>

---

## About

WebNAS provides a browser-based administration interface for Linux systems. It combines file management, services, users and groups, networking, containers, logs, automation, infrastructure integrations and modular administration tools in one application.

## Installation

### Requirements

- Linux with `systemd`
- `root` or `sudo` access
- Python **3.14**
- Node.js + npm
- `rsync`
- `openssl`
- supported package manager: `apt`, `dnf` or `yum`

### Quick install

The canonical installer entrypoint is `install.sh` in the root of the `main` branch:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

### Install from a cloned repository

```bash
git clone https://github.com/chmajster/Algen-server-web-explorer-panel.git
cd Algen-server-web-explorer-panel
sudo ./install.sh
```

### Custom port

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --port 8080
```

### Non-interactive installation

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --yes
```

### Portable mode

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --portable
```

### Update

Run the same root installer again:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

The installer detects an existing WebNAS installation and exposes the supported update/reinstall/backup/remove/restart actions.

## Installer layout

`install.sh` in the repository root is the stable public entrypoint. Installer implementation details and alternate modes remain under `install/`.

```text
Algen-server-web-explorer-panel/
├── install.sh                    # canonical public installer entrypoint
└── install/
    ├── install.sh                # installer launcher implementation
    ├── install-standard.sh       # standard installation implementation
    ├── install-standard-menu.sh  # existing-install action menu
    └── install-portable.sh       # portable mode
```

Users and documentation should invoke only the root `install.sh`. Files under `install/*` are internal installer components and may be called by the root launcher.

## First login

Fresh standard installations use the **Local database** authentication mode and create the initial administrator:

```text
Username: chris
Password: 1
Role: admin
```

Change the default password immediately after the first login.

WebNAS is available by default at:

```text
https://SERVER_IP:5000
```

A self-signed TLS certificate may be generated during the first installation, so the browser can display a certificate warning until the certificate is trusted or replaced.

## Documentation

Full project documentation is maintained under [`docs/`](docs/):

- [Full project overview](docs/README.md)
- [Installation and troubleshooting](docs/INSTALL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Authentication](docs/AUTHENTICATION.md)
- [LDAP authentication](docs/LDAP_AUTHENTICATION.md)
- [Modules](docs/MODULES.md)
- [Testing](docs/testing.md)
- [Deployment](docs/deployment.md)

## Development

```bash
git clone https://github.com/chmajster/Algen-server-web-explorer-panel.git
cd Algen-server-web-explorer-panel
```

The backend is based on FastAPI/Python and the frontend on React/TypeScript/Vite. CI validates backend tests, frontend lint/type/build, security checks and installer workflows.

---

<div align="center">

**WebNAS — one interface for managing your Linux server.**

</div>
