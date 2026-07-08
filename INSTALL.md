# Ubuntu/Debian Installation

```bash
sudo ./scripts/install.sh
```

The installer:

- checks whether port `5000` is free,
- installs Python, Node/npm, PAM headers, and build tools,
- copies the app to `/opt/webnas`,
- creates `/etc/webnas/config.yaml` with port `5000`,
- creates `/var/lib/webnas` and `/var/log/webnas`,
- builds the React frontend,
- installs and enables `webnas.service`,
- prints the service status and access URL.

After installation, open:

```text
http://IP_SERWERA:5000
```

Manual service commands:

```bash
sudo systemctl status webnas
sudo systemctl restart webnas
sudo journalctl -u webnas -f
```

Update:

```bash
sudo ./scripts/update.sh
```

Uninstall:

```bash
sudo ./scripts/uninstall.sh
```
