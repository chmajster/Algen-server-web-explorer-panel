#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: str, marker: str, content: str) -> None:
    replace_once(path, marker, marker + content)


# The root server must use the extended typed policy, never the historical broad adapters.
replace_once(
    "backend/app/privileged_broker/server.py",
    "from .policy import dispatch\n",
    "from .extended_policy import dispatch\n",
)

# Correct Linux shell quoting and the exact mount argv shape in the extended policy.
insert_after("backend/app/privileged_broker/extended_policy.py", "import re\n", "import shlex\n")
replace_once(
    "backend/app/privileged_broker/extended_policy.py",
    '''    if tool == "mount":\n        if len(args) != 7 or args[0] != "-t" or args[2] != "-o" or args[1] not in {"cifs", "nfs", "davfs"}:\n            raise base.PolicyError("unsupported mount command")\n        filesystem = args[1]\n        options = _validated_mount_options(args[3])\n        remote = _clean_token(args[4], "mount remote", limit=4096)\n        target = _mount_root(args[5] if len(args) == 6 else args[6])\n        # Historical call shape is: mount -t TYPE -o OPTIONS REMOTE TARGET.\n        if len(args) == 7:\n            # Reject an unexpected extra field rather than guessing at it.\n            raise base.PolicyError("invalid mount argument count")\n        return runner([base._resolve_tool("mount"), "-t", filesystem, "-o", options, remote, target], None, timeout)\n''',
    '''    if tool == "mount":\n        if len(args) != 6 or args[0] != "-t" or args[2] != "-o" or args[1] not in {"cifs", "nfs", "davfs"}:\n            raise base.PolicyError("unsupported mount command")\n        filesystem = args[1]\n        options = _validated_mount_options(args[3])\n        remote = _clean_token(args[4], "mount remote", limit=4096)\n        target = _mount_root(args[5])\n        return runner([base._resolve_tool("mount"), "-t", filesystem, "-o", options, remote, target], None, timeout)\n''',
)
replace_once(
    "backend/app/privileged_broker/extended_policy.py",
    '''    command_text = " ".join(subprocess.list2cmdline([item]) for item in command)\n''',
    '''    command_text = " ".join(shlex.quote(item) for item in command)\n''',
)
replace_once(
    "backend/app/privileged_broker/extended_policy.py",
    "subprocess.list2cmdline([str(log_path)])",
    "shlex.quote(str(log_path))",
)
# The same path expression occurs more than once after the first exact replacement.
policy_path = ROOT / "backend/app/privileged_broker/extended_policy.py"
policy_text = policy_path.read_text(encoding="utf-8").replace("subprocess.list2cmdline([str(progress)])", "shlex.quote(str(progress))")
policy_text = policy_text.replace("subprocess.list2cmdline([unit_name])", "shlex.quote(unit_name)")
policy_path.write_text(policy_text, encoding="utf-8")

# Package Center: keep planning/cancellation in the API process but route each actual
# package/systemd command and trusted hook through the root broker.
insert_after(
    "backend/app/package_center/executor.py",
    "from .package_managers import resolve_package_manager_executable\n",
    "from ..config import get_config\nfrom ..privileged_broker.runtime import broker_command, broker_required, module_hook\n",
)
replace_once(
    "backend/app/package_center/executor.py",
    '''def _shared_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:\n    """Create files visible both inside WebNAS' PrivateTmp and transient admin units."""\n\n    try:\n        SHARED_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)\n        os.chmod(SHARED_RUNTIME_ROOT, 0o700)\n        return tempfile.TemporaryDirectory(prefix=prefix, dir=SHARED_RUNTIME_ROOT)\n    except OSError:\n        # Non-root tests and non-systemd environments use the normal temporary directory.\n        return tempfile.TemporaryDirectory(prefix=prefix)\n''',
    '''def _shared_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:\n    """Create package files in a directory visible to the privileged broker."""\n\n    if broker_required():\n        runtime = Path(get_config().paths.data_dir) / "package-center-runtime"\n        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)\n        os.chmod(runtime, 0o700)\n        return tempfile.TemporaryDirectory(prefix=prefix, dir=runtime)\n    try:\n        SHARED_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)\n        os.chmod(SHARED_RUNTIME_ROOT, 0o700)\n        return tempfile.TemporaryDirectory(prefix=prefix, dir=SHARED_RUNTIME_ROOT)\n    except OSError:\n        return tempfile.TemporaryDirectory(prefix=prefix)\n''',
)
replace_once(
    "backend/app/package_center/executor.py",
    '''def _run(args: list[str], timeout: int, log: LogCallback) -> None:\n    if not args or shutil.which(args[0]) is None:\n        raise RuntimeError(f"Required executable is unavailable: {args[0] if args else 'unknown'}")\n    log("command", " ".join(args))\n    execution_args = _transient_admin_command(args, timeout)\n''',
    '''def _run(args: list[str], timeout: int, log: LogCallback) -> None:\n    if not args:\n        raise RuntimeError("Required executable is unavailable: unknown")\n    log("command", " ".join(args))\n    if broker_required():\n        broker_result = broker_command(args, timeout=timeout, actor="package-center")\n        if broker_result is not None:\n            for line in broker_result.stdout.splitlines():\n                log("stdout", redact(line))\n            for line in broker_result.stderr.splitlines():\n                log("stderr", redact(line))\n            if broker_result.returncode != 0:\n                raise CommandExecutionError(Path(args[0]).name, broker_result.returncode, broker_result.stderr or broker_result.stdout)\n            return\n    if shutil.which(args[0]) is None:\n        raise RuntimeError(f"Required executable is unavailable: {args[0]}")\n    execution_args = _transient_admin_command(args, timeout)\n''',
)
replace_once(
    "backend/app/package_center/executor.py",
    '''def _run_hook(manifest: ModuleManifest, action: str, log: LogCallback) -> None:\n    script = module_script(manifest.id, action)\n    if not script:\n        return\n    args = [sys.executable, str(script)] if script.suffix == ".py" else ["/bin/bash", str(script)]\n    _run(args, 1800 if action in {"prepare", "rollback", "health"} else 300, log)\n''',
    '''def _run_hook(manifest: ModuleManifest, action: str, log: LogCallback) -> None:\n    script = module_script(manifest.id, action)\n    if not script:\n        return\n    if broker_required():\n        result = module_hook(manifest.id, action, actor="package-center")\n        for line in result.stdout.splitlines():\n            log("stdout", redact(line))\n        for line in result.stderr.splitlines():\n            log("stderr", redact(line))\n        if result.returncode != 0:\n            raise CommandExecutionError(f"{manifest.id}:{action}", result.returncode, result.stderr or result.stdout)\n        return\n    args = [sys.executable, str(script)] if script.suffix == ".py" else ["/bin/bash", str(script)]\n    _run(args, 1800 if action in {"prepare", "rollback", "health"} else 300, log)\n''',
)
replace_once(
    "backend/app/package_center/executor.py",
    '''    if manifest.requires_root and hasattr(os, "geteuid") and os.geteuid() != 0:\n        raise PermissionError("Package operations require the WebNAS service to run as root")\n''',
    '''    if manifest.requires_root and hasattr(os, "geteuid") and os.geteuid() != 0 and not broker_required():\n        raise PermissionError("Package operations require root or the privileged broker")\n''',
)

# Settings/local identity/system power: keep all validation/RBAC where it is, but the
# final mutation argv is translated to a typed broker request in required mode.
insert_after(
    "backend/app/settings.py",
    "from .path_policy import resolve_user_path\n",
    "from .privileged_broker.runtime import broker_command, broker_required, filesystem_mkdir, update_service\n",
)
replace_once(
    "backend/app/settings.py",
    '''def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:\n    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=60, check=False)\n    if result.returncode != 0:\n        raise HTTPException(400, result.stderr.strip() or "System command failed")\n    return result\n''',
    '''def _run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:\n    result = None\n    if broker_required():\n        result = broker_command(args, input_text=input_text, timeout=60, actor="settings-admin")\n    if result is None:\n        result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=60, check=False)\n    if result.returncode != 0:\n        raise HTTPException(400, result.stderr.strip() or "System command failed")\n    return result\n''',
)
replace_once(
    "backend/app/settings.py",
    '''    if payload.create_home:\n        Path(pwd.getpwnam(username).pw_dir).mkdir(parents=True, exist_ok=True)\n''',
    '''    if payload.create_home:\n        home_path = Path(pwd.getpwnam(username).pw_dir)\n        if broker_required():\n            filesystem_mkdir(home_path, mode=0o750, owner=username, actor="settings-admin")\n        else:\n            home_path.mkdir(parents=True, exist_ok=True)\n''',
)
replace_once(
    "backend/app/settings.py",
    '''def _start_update_process(update_config: bool, *, actor: str, npm_audit_fix: bool = False) -> dict:\n    settings_dir = _auto_update_path().parent\n''',
    '''def _start_update_process(update_config: bool, *, actor: str, npm_audit_fix: bool = False) -> dict:\n    if broker_required():\n        try:\n            result = update_service(update_config=update_config, npm_audit_fix=npm_audit_fix, actor=actor)\n        except RuntimeError as error:\n            raise HTTPException(503, str(error)) from error\n        _audit(actor, "download_update", f"unit={result['unit']} pid={result.get('pid') or 'pending'}")\n        return {"ok": True, "pid": result.get("pid"), "unit": result["unit"], "log": result.get("log", "")}\n    settings_dir = _auto_update_path().parent\n''',
)

# Samba: configuration files are symbolic broker targets; share-directory ownership
# and mode changes are constrained to the broker filesystem roots; smbpasswd is typed.
insert_after(
    "backend/app/app_store/samba.py",
    "from ..path_policy import resolve_user_path\n",
    "from ..config import get_config\nfrom ..privileged_broker.runtime import (\n    broker_command, broker_required, filesystem_chmod, filesystem_mkdir, managed_file_write, ownership_change,\n)\n",
)
replace_once(
    "backend/app/app_store/samba.py",
    '''def _run(args: list[str], *, input_text: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:\n    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False)\n    if result.returncode != 0:\n        output = result.stderr.strip() or result.stdout.strip()\n        raise HTTPException(400, output or f"{Path(args[0]).name} failed with exit code {result.returncode}")\n    return result\n''',
    '''def _run(args: list[str], *, input_text: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:\n    result = None\n    if broker_required():\n        result = broker_command(args, input_text=input_text, timeout=timeout, actor="samba-manager")\n    if result is None:\n        result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False)\n    if result.returncode != 0:\n        output = result.stderr.strip() or result.stdout.strip()\n        raise HTTPException(400, output or f"{Path(args[0]).name} failed with exit code {result.returncode}")\n    return result\n''',
)
insert_after(
    "backend/app/app_store/samba.py",
    '''def read_samba_config() -> SambaConfig:\n    payload = state.read_state("samba")\n    return SambaConfig.model_validate(payload.get("config") or {})\n\n''',
    '''def _safe_legacy_backup(source: Path, stem: str, now: str | None = None) -> Path | None:\n    if not source.exists():\n        return None\n    if not broker_required():\n        return None\n    stamp = now or time.strftime("%Y%m%d-%H%M%S")\n    root = Path(get_config().paths.data_dir) / "module-backups" / "samba" / "legacy"\n    root.mkdir(parents=True, exist_ok=True, mode=0o700)\n    target = root / f"{stem}-{stamp}.conf"\n    try:\n        target.write_bytes(source.read_bytes())\n    except OSError:\n        return None\n    os.chmod(target, 0o600)\n    return target\n\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''def backup_smb_conf(now: str | None = None) -> Path | None:\n    if not SAMBA_CONF.exists():\n        return None\n    stamp = now or time.strftime("%Y%m%d-%H%M%S")\n    backup = SAMBA_CONF.with_name(f"smb.conf.webnas-backup-{stamp}")\n    shutil.copy2(SAMBA_CONF, backup)\n    return backup\n''',
    '''def backup_smb_conf(now: str | None = None) -> Path | None:\n    if broker_required():\n        return _safe_legacy_backup(SAMBA_CONF, "smb", now)\n    if not SAMBA_CONF.exists():\n        return None\n    stamp = now or time.strftime("%Y%m%d-%H%M%S")\n    backup = SAMBA_CONF.with_name(f"smb.conf.webnas-backup-{stamp}")\n    shutil.copy2(SAMBA_CONF, backup)\n    return backup\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''def backup_algen_smb_conf(now: str | None = None) -> Path | None:\n    if not SAMBA_ALGEN_CONF.exists():\n        return None\n    stamp = now or time.strftime("%Y%m%d-%H%M%S")\n    backup = SAMBA_ALGEN_CONF.with_name(f"algen-shares.conf.backup-{stamp}")\n    shutil.copy2(SAMBA_ALGEN_CONF, backup)\n    return backup\n''',
    '''def backup_algen_smb_conf(now: str | None = None) -> Path | None:\n    if broker_required():\n        return _safe_legacy_backup(SAMBA_ALGEN_CONF, "algen-shares", now)\n    if not SAMBA_ALGEN_CONF.exists():\n        return None\n    stamp = now or time.strftime("%Y%m%d-%H%M%S")\n    backup = SAMBA_ALGEN_CONF.with_name(f"algen-shares.conf.backup-{stamp}")\n    shutil.copy2(SAMBA_ALGEN_CONF, backup)\n    return backup\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")\n    try:\n        with temporary.open("w", encoding="utf-8") as handle:\n            handle.write(text)\n            handle.flush()\n            os.fsync(handle.fileno())\n        os.chmod(temporary, (SAMBA_CONF.stat().st_mode & 0o777) if existed else 0o600)\n        os.replace(temporary, SAMBA_CONF)\n    finally:\n        if temporary.exists():\n            temporary.unlink()\n''',
    '''    if broker_required():\n        mode = (SAMBA_CONF.stat().st_mode & 0o777) if existed else 0o644\n        managed_file_write("samba_main", text, actor="samba-manager", mode=mode if mode in {0o600, 0o640, 0o644} else 0o644)\n        return\n    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")\n    try:\n        with temporary.open("w", encoding="utf-8") as handle:\n            handle.write(text)\n            handle.flush()\n            os.fsync(handle.fileno())\n        os.chmod(temporary, (SAMBA_CONF.stat().st_mode & 0o777) if existed else 0o600)\n        os.replace(temporary, SAMBA_CONF)\n    finally:\n        if temporary.exists():\n            temporary.unlink()\n''',
)
# The same direct-write shape appears in remove_smb_conf_include; replace that block separately by nearby unique prelude.
replace_once(
    "backend/app/app_store/samba.py",
    '''    updated = "\\n".join(lines).rstrip() + "\\n"\n    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")\n''',
    '''    updated = "\\n".join(lines).rstrip() + "\\n"\n    if broker_required():\n        mode = SAMBA_CONF.stat().st_mode & 0o777\n        managed_file_write("samba_main", updated, actor="samba-manager", mode=mode if mode in {0o600, 0o640, 0o644} else 0o644)\n        return\n    temporary = SAMBA_CONF.with_name(f".{SAMBA_CONF.name}.{uuid4().hex}.tmp")\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''    if share.create_directory:\n        resolved.mkdir(parents=True, exist_ok=True)\n''',
    '''    if share.create_directory:\n        if broker_required():\n            filesystem_mkdir(resolved, mode=int(share.directory_mode, 8) if share.directory_mode else 0o750, actor="samba-manager")\n        else:\n            resolved.mkdir(parents=True, exist_ok=True)\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''    if owner or group:\n        uid = -1\n        gid = -1\n        if owner:\n            import pwd\n\n            uid = pwd.getpwnam(owner).pw_uid\n        if group:\n            import grp\n\n            gid = grp.getgrnam(group).gr_gid\n        os.chown(resolved, uid, gid)\n    if share.directory_mode:\n        if not MASK_RE.fullmatch(share.directory_mode):\n            raise HTTPException(400, "Invalid directory permission mode")\n        os.chmod(resolved, int(share.directory_mode, 8))\n''',
    '''    if owner or group:\n        if broker_required():\n            ownership_change(resolved, owner=owner, group=group, actor="samba-manager")\n        else:\n            uid = -1\n            gid = -1\n            if owner:\n                import pwd\n\n                uid = pwd.getpwnam(owner).pw_uid\n            if group:\n                import grp\n\n                gid = grp.getgrnam(group).gr_gid\n            os.chown(resolved, uid, gid)\n    if share.directory_mode:\n        if not MASK_RE.fullmatch(share.directory_mode):\n            raise HTTPException(400, "Invalid directory permission mode")\n        mode = int(share.directory_mode, 8)\n        if broker_required():\n            filesystem_chmod(resolved, mode, actor="samba-manager")\n        else:\n            os.chmod(resolved, mode)\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''    SAMBA_ALGEN_CONF.write_text(preview["config"], encoding="utf-8")\n''',
    '''    if broker_required():\n        managed_file_write("samba_shares", preview["config"], actor="samba-manager", mode=0o644)\n    else:\n        SAMBA_ALGEN_CONF.write_text(preview["config"], encoding="utf-8")\n''',
)
replace_once(
    "backend/app/app_store/samba.py",
    '''    shutil.copy2(backup, SAMBA_ALGEN_CONF)\n''',
    '''    if broker_required():\n        managed_file_write("samba_shares", backup.read_text(encoding="utf-8", errors="replace"), actor="samba-manager", mode=0o644)\n    else:\n        shutil.copy2(backup, SAMBA_ALGEN_CONF)\n''',
)

# Network mounts: mount/umount use the typed command adapter; persistent units are
# reconstructed by the root broker rather than accepting arbitrary unit text.
insert_after(
    "backend/app/network_mounts.py",
    "from .update_coordination import operation_admission\n",
    "from .privileged_broker.runtime import broker_command, broker_required, filesystem_mkdir, mount_unit_action\n",
)
replace_once(
    "backend/app/network_mounts.py",
    '''def run_command(args: list[str], *, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:\n    return subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)\n''',
    '''def run_command(args: list[str], *, timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess[str]:\n    if broker_required():\n        result = broker_command(args, input_text=input_text, timeout=timeout, actor="network-mounts")\n        if result is not None:\n            return result\n    return subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)\n''',
)
replace_once(
    "backend/app/network_mounts.py",
    '''def _prepare_mount_directory(mount: dict) -> None:\n    MOUNT_BASE_DIR.mkdir(parents=True, exist_ok=True)\n    os.chmod(MOUNT_BASE_DIR, 0o711)\n    point = Path(mount["mount_point"])\n    point.mkdir(parents=True, exist_ok=True)\n    os.chmod(point, 0o750)\n''',
    '''def _prepare_mount_directory(mount: dict) -> None:\n    point = Path(mount["mount_point"])\n    if broker_required():\n        filesystem_mkdir(MOUNT_BASE_DIR, mode=0o711, actor="network-mounts")\n        filesystem_mkdir(point, mode=0o750, actor="network-mounts")\n        return\n    MOUNT_BASE_DIR.mkdir(parents=True, exist_ok=True)\n    os.chmod(MOUNT_BASE_DIR, 0o711)\n    point.mkdir(parents=True, exist_ok=True)\n    os.chmod(point, 0o750)\n''',
)
# Inject early broker branches into persistent unit functions without changing the legacy implementation.
replace_once(
    "backend/app/network_mounts.py",
    '''def write_systemd_units(mount: dict) -> list[str]:\n    units = generate_systemd_units(mount)\n''',
    '''def write_systemd_units(mount: dict) -> list[str]:\n    if broker_required():\n        fs_type = {"smb": "cifs", "nfs": "nfs", "sshfs": "fuse.sshfs", "webdav": "davfs"}[mount["type"]]\n        result = mount_unit_action(\n            "apply", mount_id=str(mount["id"]), mount_point=str(mount["mount_point"]), remote=remote_spec(mount),\n            fs_type=fs_type, options=",".join(mount_options(mount)), automount=bool(mount.get("config", {}).get("automount")),\n            actor="network-mounts",\n        )\n        if result.returncode != 0:\n            raise HTTPException(400, result.stderr.strip() or "Could not install persistent mount unit")\n        return []\n    units = generate_systemd_units(mount)\n''',
)
replace_once(
    "backend/app/network_mounts.py",
    '''def remove_systemd_units(mount: dict) -> None:\n    names = set(generated_unit_names(mount))\n''',
    '''def remove_systemd_units(mount: dict) -> None:\n    if broker_required():\n        result = mount_unit_action(\n            "remove", mount_id=str(mount["id"]), mount_point=str(mount["mount_point"]), actor="network-mounts"\n        )\n        if result.returncode != 0:\n            raise HTTPException(400, result.stderr.strip() or "Could not remove persistent mount unit")\n        return\n    names = set(generated_unit_names(mount))\n''',
)

# SMART/NVMe probes often require root even though they are read-only; expose only those
# exact probe shapes via the broker so Storage Manager does not regress after UID drop.
insert_after(
    "backend/app/modules/storage_manager/service.py",
    "from ...local_disks import NETWORK_FILESYSTEMS, PSEUDO_FILESYSTEMS, parse_proc_mounts\n",
    "from ...privileged_broker.runtime import broker_required, storage_probe\n",
)
replace_once(
    "backend/app/modules/storage_manager/service.py",
    '''    def _run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:\n        executable = self._tool_resolver(name) if name in ALLOWED_TOOLS else None\n        if executable is None:\n            return None\n        try:\n            return self._runner([executable, *args], timeout)\n''',
    '''    def _run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:\n        executable = self._tool_resolver(name) if name in ALLOWED_TOOLS else None\n        if executable is None:\n            return None\n        try:\n            if broker_required() and name in {"smartctl", "nvme"}:\n                result = storage_probe(name, list(args), timeout=timeout)\n                return CommandResult(result.returncode, result.stdout, result.stderr)\n            return self._runner([executable, *args], timeout)\n''',
)

# Production services: ensure the service account and broker socket exist, own only
# WebNAS runtime/state paths, and run the normal API without UID 0.
replace_once(
    "scripts/webnas_release.py",
    "import os\n",
    "import os\nimport grp\nimport pwd\n",
)
replace_once(
    "scripts/webnas_release.py",
    '''    def write_units(self) -> None:\n        runtime = self.runtime_dir\n        runtime.mkdir(parents=True, exist_ok=True)\n        data_dir = config_value(self.config, "paths", "data_dir", "/var/lib/webnas")\n        log_dir = config_value(self.config, "paths", "log_dir", "/var/log/webnas")\n''',
    '''    def write_units(self) -> None:\n        runtime = self.runtime_dir\n        runtime.mkdir(parents=True, exist_ok=True)\n        data_dir = config_value(self.config, "paths", "data_dir", "/var/lib/webnas")\n        log_dir = config_value(self.config, "paths", "log_dir", "/var/log/webnas")\n        temp_dir = config_value(self.config, "paths", "temp_dir", "/var/lib/webnas/tmp")\n        try:\n            grp.getgrnam(self.service_user)\n        except KeyError:\n            command("groupadd", "--system", self.service_user)\n        try:\n            pwd.getpwnam(self.service_user)\n        except KeyError:\n            command("useradd", "--system", "--gid", self.service_user, "--home-dir", data_dir, "--shell", "/usr/sbin/nologin", self.service_user)\n        for writable in (Path(data_dir), Path(log_dir), Path(temp_dir), runtime, self.root):\n            writable.mkdir(parents=True, exist_ok=True)\n            command("chown", "-R", f"{self.service_user}:{self.service_user}", str(writable))\n        socket_unit = self.systemd_dir / "webnas-privileged.socket"\n        broker_unit = self.systemd_dir / "webnas-privileged.service"\n        atomic_write(socket_unit, "\\n".join([\n            "[Unit]", "Description=WebNAS privileged operation broker socket", "",\n            "[Socket]", "ListenStream=/run/webnas/privileged.sock", "SocketUser=root", f"SocketGroup={self.service_user}",\n            "SocketMode=0660", "DirectoryMode=0750", "RemoveOnStop=true", "",\n            "[Install]", "WantedBy=sockets.target", "",\n        ]))\n        atomic_write(broker_unit, "\\n".join([\n            "[Unit]", "Description=WebNAS privileged operation broker", "Requires=webnas-privileged.socket",\n            "After=webnas-privileged.socket", "", "[Service]", "Type=simple", "User=root", "Group=root",\n            f"Environment=PYTHONPATH={self.release / 'backend'}", f"Environment=WEBNAS_CONFIG={self.config}",\n            f"ExecStart={self.release / 'backend/.venv/bin/python'} -m app.privileged_broker.server",\n            "NoNewPrivileges=false", "PrivateTmp=true", "ProtectSystem=false", "ProtectHome=false",\n            "ProtectKernelTunables=true", "ProtectKernelModules=true", "ProtectControlGroups=true", "",\n        ]))\n        command("systemctl", "daemon-reload")\n        command("systemctl", "enable", "--now", "webnas-privileged.socket")\n''',
)
replace_once(
    "scripts/webnas_release.py",
    '''                "User=root",\n                "Group=root",\n                "NoNewPrivileges=false",\n''',
    '''                f"User={self.service_user}",\n                f"Group={self.service_user}",\n                "Environment=WEBNAS_PRIVILEGED_BROKER=required",\n                "Requires=webnas-privileged.socket",\n                "After=webnas-privileged.socket",\n                "NoNewPrivileges=true",\n''',
)
replace_once(
    "scripts/webnas_release.py",
    '''                "RestrictSUIDSGID=false",\n''',
    '''                "RestrictSUIDSGID=true",\n''',
)

# Legacy unit follows the same privilege boundary. Installer/release tooling remains root.
service = ROOT / "packaging/webnas.service"
service_text = service.read_text(encoding="utf-8")
service_text = service_text.replace("User=root\nGroup=root\n", "User=webnas\nGroup=webnas\nEnvironment=WEBNAS_PRIVILEGED_BROKER=required\nRequires=webnas-privileged.socket\nAfter=webnas-privileged.socket\n")
service_text = service_text.replace("NoNewPrivileges=false", "NoNewPrivileges=true")
service_text = service_text.replace("RestrictSUIDSGID=false", "RestrictSUIDSGID=true")
service.write_text(service_text, encoding="utf-8")

print("Privilege migration transformations applied")
