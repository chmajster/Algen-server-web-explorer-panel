from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path


ACCOUNT = "webnas-ansible"
ROOT = Path("/var/lib/webnas/ansible-controller")


def run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False, shell=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {args[0]}")


try:
    entry = pwd.getpwnam(ACCOUNT)
except KeyError:
    useradd = shutil.which("useradd")
    if not useradd:
        raise RuntimeError("useradd is unavailable")
    run([useradd, "--system", "--create-home", "--home-dir", str(ROOT / "home"), "--shell", "/usr/sbin/nologin", "--user-group", ACCOUNT])
    entry = pwd.getpwnam(ACCOUNT)

for directory in (ROOT, ROOT / "home", ROOT / "config", ROOT / "projects", ROOT / "runs", ROOT / "tmp", ROOT / "known-hosts", ROOT / "backups"):
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    os.chown(directory, entry.pw_uid, entry.pw_gid)

config = ROOT / "config" / "ansible.cfg"
if not config.exists():
    config.write_text(
        "[defaults]\n"
        f"inventory = {ROOT / 'runs'}\n"
        f"private_key_file = {ROOT / 'home' / '.ssh' / 'id_ed25519'}\n"
        "host_key_checking = True\n"
        "retry_files_enabled = False\n"
        "interpreter_python = auto_silent\n"
        "nocows = True\n"
        "stdout_callback = default\n"
        "bin_ansible_callbacks = False\n"
        "[ssh_connection]\n"
        "pipelining = True\n",
        encoding="utf-8",
    )
    os.chmod(config, 0o600)
    os.chown(config, entry.pw_uid, entry.pw_gid)

ssh_dir = ROOT / "home" / ".ssh"
ssh_dir.mkdir(mode=0o700, exist_ok=True)
os.chmod(ssh_dir, 0o700)
os.chown(ssh_dir, entry.pw_uid, entry.pw_gid)
key = ssh_dir / "id_ed25519"
if not key.exists():
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise RuntimeError("ssh-keygen is unavailable")
    run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", "webnas-ansible", "-f", str(key)])
for item in (key, key.with_suffix(".pub")):
    if item.exists():
        os.chown(item, entry.pw_uid, entry.pw_gid)
        os.chmod(item, 0o600 if item == key else 0o644)

print("webnas-ansible account and private controller directories are ready")
