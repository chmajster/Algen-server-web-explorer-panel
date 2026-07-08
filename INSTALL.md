# Ubuntu/Debian Installation

```bash
sudo ./scripts/install.sh
```

The installer:

- checks whether port `5000` is free,
- installs Python, Node/npm, PAM headers, `rsync`, and build tools,
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

`rsync` is required for File Manager copy and move operations. The installer checks for `rsync`, PAM, and the Linux account-management tools used by the Settings app. If a transfer fails, open the Transfers panel in the UI or inspect:

```bash
sudo journalctl -u webnas -f
```

Transfers can be cancelled from the UI or through:

```text
POST /api/files/tasks/{task_id}/cancel
```

Update:

```bash
sudo ./scripts/update.sh
```

Uninstall:

```bash
sudo ./scripts/uninstall.sh
```
