from __future__ import annotations

import shutil


daemon = "cron" if shutil.which("cron") else "crond" if shutil.which("crond") else "not detected"
crontab = shutil.which("crontab") or "not detected"
print(f"Cron Manager activated; daemon={daemon}; crontab={crontab}")
