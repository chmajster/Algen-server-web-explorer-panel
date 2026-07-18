from __future__ import annotations

import os
import pwd
import shutil
from pathlib import Path

required = ("ansible", "ansible-playbook", "ansible-inventory", "ssh", "ssh-keygen", "nmap", "git")
missing = [name for name in required if not shutil.which(name)]
if missing:
    raise SystemExit(f"Missing controller executables: {', '.join(missing)}")
try:
    account = pwd.getpwnam("webnas-ansible")
except KeyError as error:
    raise SystemExit("webnas-ansible account is missing") from error
if account.pw_uid == 0 or account.pw_shell not in {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"}:
    raise SystemExit("webnas-ansible account is not safely isolated")
root = Path("/var/lib/webnas/ansible-controller")
if not root.is_dir() or os.stat(root).st_mode & 0o077:
    raise SystemExit("controller data directory permissions are not 0700")
print("Ansible controller health check passed")
