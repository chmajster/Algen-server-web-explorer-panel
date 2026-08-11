#!/usr/bin/env python3.14
from __future__ import annotations

import shutil

if not (shutil.which("cron") or shutil.which("crond") or shutil.which("crontab")):
    raise SystemExit("cron/crond and crontab are unavailable")
print("Cron Manager host capability detected")
