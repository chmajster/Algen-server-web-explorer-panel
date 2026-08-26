#!/usr/bin/env python3.14
from __future__ import annotations

import shutil

if not (shutil.which("kea-dhcp4") or shutil.which("dhcpd")):
    raise SystemExit("Kea DHCP4 or ISC dhcpd is unavailable")
print("DHCP backend detected")
