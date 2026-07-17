from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ... import apps
from ...config import get_config
from ...package_center.executor import redact
from ...package_center.models import ModuleBackup, ModuleDiagnostic, ModuleHealth, ModuleStatus, ModuleValidationResult, PackageAction, api_error
from .base import CancelCallback, LogCallback, ModuleProvider, ProgressCallback

BACKUP_ID_RE = re.compile(r"^[a-f0-9]{32}$")
GLOBAL_OPTIONS = {
    "workgroup", "server string", "netbios name", "security", "map to guest", "server min protocol", "server max protocol",
    "interfaces", "bind interfaces only", "log level", "max log size", "deadtime", "load printers", "printing", "disable spoolss",
    "unix extensions", "wide links", "follow symlinks",
}
SMB1_VALUES = {"nt1", "lanman1", "lanman2", "core", "coreplus"}


def parse_smbstatus_json(text: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(text or "{}")
    except json.JSONDecodeError:
        return []
    sessions = raw.get("sessions") or {}
    tcons = raw.get("tcons") or raw.get("tree_connects") or {}
    open_files = raw.get("open_files") or {}
    result: list[dict[str, Any]] = []
    entries = sessions.values() if isinstance(sessions, dict) else sessions if isinstance(sessions, list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("session_id") or entry.get("pid") or entry.get("id") or "")
        shares = [str(item.get("share_name") or item.get("service") or "") for item in (tcons.values() if isinstance(tcons, dict) else []) if isinstance(item, dict) and str(item.get("session_id") or item.get("pid") or "") == session_id]
        files = sum(1 for item in (open_files.values() if isinstance(open_files, dict) else []) if isinstance(item, dict) and str(item.get("session_id") or item.get("pid") or "") == session_id)
        result.append({
            "id": session_id,
            "username": str(entry.get("username") or entry.get("user") or ""),
            "client": str(entry.get("hostname") or entry.get("machine") or ""),
            "ip": str(entry.get("remote_machine") or entry.get("ip_addr") or entry.get("ip") or ""),
            "protocol": str(entry.get("protocol_ver") or entry.get("protocol") or ""),
            "share": ", ".join(filter(None, shares)),
            "open_files": files,
            "connected_at": entry.get("connected_at") or entry.get("start_time"),
            "pid": entry.get("pid"),
        })
    return result


def parse_smbstatus_text(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    in_sessions = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("pid") and "username" in stripped.lower():
            in_sessions = True
            continue
        if in_sessions and (not stripped or stripped.startswith("---")):
            continue
        if in_sessions and stripped.lower().startswith("service"):
            break
        if not in_sessions:
            continue
        parts = stripped.split()
        if len(parts) >= 4 and parts[0].isdigit():
            result.append({"id": parts[0], "pid": int(parts[0]), "username": parts[1], "client": parts[3], "ip": parts[3], "protocol": parts[-1] if len(parts) > 5 else "", "share": "", "open_files": 0, "connected_at": None})
    return result


def parse_smb_conf(text: str) -> apps.SambaConfig:
    if len(text.encode("utf-8")) > 1_000_000:
        raise ValueError("Samba configuration exceeds the 1 MB import limit")
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            if not apps.SHARE_RE.fullmatch(current.removesuffix("$")) and current.lower() != "global":
                raise ValueError(f"Invalid Samba section: {current}")
            sections.setdefault(current, {})
            continue
        if "=" not in line or not current:
            raise ValueError("Malformed Samba configuration line")
        key, value = (item.strip() for item in line.split("=", 1))
        if not key or any(char in value for char in "\r\n\x00[]"):
            raise ValueError("Invalid Samba option")
        sections[current][key.lower()] = value
    global_options = {key: value for key, value in sections.pop("global", {}).items() if key in GLOBAL_OPTIONS}
    shares: list[apps.SambaShare] = []
    yes = {"yes", "true", "1"}
    for name, values in sections.items():
        allowed = {"path", "comment", "browseable", "read only", "guest ok", "create mask", "directory mask", "valid users", "read list", "write list", "admin users", "force user", "force group", "force create mode", "force directory mode", "inherit permissions", "veto files", "vfs objects", "recycle:repository", "recycle:keeptree", "recycle:versions"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported Samba options in {name}: {', '.join(sorted(unknown))}")
        vfs_objects = values.get("vfs objects", "").split()
        unknown_vfs = set(vfs_objects) - apps.SAFE_SAMBA_VFS_OBJECTS
        if unknown_vfs:
            raise ValueError(f"Unsupported Samba VFS objects in {name}: {', '.join(sorted(unknown_vfs))}")
        def tokens(key: str) -> list[str]:
            return values.get(key, "").split()
        valid = tokens("valid users")
        shares.append(apps.SambaShare(
            name=name.removesuffix("$"), path=values.get("path", ""), comment=values.get("comment", ""), hidden=name.endswith("$"),
            browseable=values.get("browseable", "yes").lower() in yes, read_only=values.get("read only", "yes").lower() in yes,
            guest_ok=values.get("guest ok", "no").lower() in yes, valid_users=[item for item in valid if not item.startswith("@")], valid_groups=[item.removeprefix("@") for item in valid if item.startswith("@")],
            read_list=tokens("read list"), write_list=tokens("write list"), admin_users=tokens("admin users"), force_user=values.get("force user") or None,
            force_group=values.get("force group") or None, force_create_mode=values.get("force create mode", ""), force_directory_mode=values.get("force directory mode", ""),
            inherit_permissions=values.get("inherit permissions", "no").lower() in yes, veto_files=values.get("veto files", ""),
            recycle_bin="recycle" in vfs_objects, recycle_versions=values.get("recycle:versions", "yes").lower() in yes, vfs_objects=vfs_objects,
            create_mask=values.get("create mask", "0664"), directory_mask=values.get("directory mask", "0775"),
        ))
    return apps.SambaConfig(shares=shares, global_options=global_options)


class SambaProvider(ModuleProvider):
    def __init__(self, actor: str = "root") -> None:
        super().__init__("samba")
        self.actor = actor

    @property
    def backup_dir(self) -> Path:
        path = Path(get_config().paths.data_dir) / "module-backups" / "samba"
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        return path

    @staticmethod
    def _version() -> str | None:
        executable = shutil.which("smbd")
        if not executable:
            return None
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=8, check=False, shell=False)
        version = re.sub(r"^Version\s+", "", result.stdout.strip(), flags=re.IGNORECASE)
        return version[:120] or None

    def get_status(self) -> ModuleStatus:
        base = super().get_status()
        raw = apps.samba_status_payload()
        sessions = self.sessions()
        users = self.users()
        services = dict(base.services)
        for definition in self.manifest.services:
            services.setdefault(definition.name, {"state": raw["services"].get(definition.name, "unavailable"), "enabled": False, "required": definition.required})
        installed = bool(raw["installed"])
        valid = bool(raw["validation"].get("ok")) if shutil.which("testparm") else None
        required_active = all(not item.get("required") or item.get("state") == "active" for item in services.values())
        health = ModuleHealth.not_installed if not installed else ModuleHealth.failed if valid is False else ModuleHealth.degraded if valid is None or not required_active else ModuleHealth.healthy
        base.installed = installed
        base.package_version = self._version() or base.package_version
        base.services = services
        base.service_state = "active" if any(item.get("state") == "active" for item in services.values()) else "inactive"
        base.configuration_valid = valid
        base.health = health
        base.health_message = "Samba is healthy" if health == ModuleHealth.healthy else "Samba configuration is invalid" if valid is False else "testparm is unavailable" if valid is None and installed else "A required Samba service is inactive" if installed else "Samba is not installed"
        smbd = services.get("smbd", {})
        base.metrics = {
            "shares": len(raw["shares"]), "sessions": len(sessions), "users": sum(1 for item in users if item["samba_enabled"]),
            "ports": raw["ports"], "managed_config": raw["managed_config"], "include_configured": raw["include_configured"],
            "uptime_seconds": smbd.get("uptime_seconds"), "last_restart": smbd.get("active_since"),
        }
        return base

    def get_config(self) -> dict[str, Any]:
        return apps.read_samba_config().model_dump()

    @staticmethod
    def _safe_global_options(options: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        cleaned: dict[str, str] = {}
        warnings: list[str] = []
        for key, value in options.items():
            option = key.strip().lower()
            text = str(value).strip()
            if option not in GLOBAL_OPTIONS:
                raise ValueError(f"Unsupported global Samba option: {option}")
            if any(char in text for char in "\r\n\x00[]") or len(text) > 300:
                raise ValueError(f"Invalid global Samba value: {option}")
            cleaned[option] = text
        min_protocol = cleaned.get("server min protocol", "SMB2").lower().replace(" ", "")
        if min_protocol in SMB1_VALUES:
            warnings.append("SMB1 is obsolete and strongly discouraged")
        if cleaned.get("wide links", "no").lower() in {"yes", "true", "1"}:
            warnings.append("Wide links can expose files outside a share")
        if cleaned.get("follow symlinks", "no").lower() in {"yes", "true", "1"}:
            warnings.append("Following symbolic links increases path exposure")
        return cleaned, warnings

    def validate_config(self, config: dict[str, Any]) -> ModuleValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        changes: list[dict[str, Any]] = []
        generated = ""
        validator_output = ""
        try:
            model = apps.SambaConfig.model_validate(config)
            model.global_options, option_warnings = self._safe_global_options(model.global_options)
            warnings.extend(option_warnings)
            current = apps.read_samba_config()
            current_by_name = {item.name.lower(): item for item in current.shares}
            next_by_name = {item.name.lower(): item for item in model.shares}
            for name in sorted(next_by_name.keys() - current_by_name.keys()):
                changes.append({"kind": "share_added", "name": next_by_name[name].name})
            for name in sorted(current_by_name.keys() - next_by_name.keys()):
                changes.append({"kind": "share_removed", "name": current_by_name[name].name})
            for name in sorted(current_by_name.keys() & next_by_name.keys()):
                if current_by_name[name].model_dump() != next_by_name[name].model_dump():
                    changes.append({"kind": "share_changed", "name": next_by_name[name].name})
            for key in sorted(set(current.global_options) | set(model.global_options)):
                if current.global_options.get(key) != model.global_options.get(key):
                    changes.append({"kind": "global_changed", "name": key, "before": current.global_options.get(key), "after": model.global_options.get(key)})
            preview = apps.preview_samba_config(self.actor, model)
            generated = preview["config"]
            validator_output = redact(f"{preview['validation'].get('stdout', '')}\n{preview['validation'].get('stderr', '')}".strip())
            if not preview["validation"].get("ok"):
                errors.append(validator_output or "testparm rejected the generated configuration")
            for share in model.shares:
                path = Path(share.path)
                if path.is_symlink():
                    warnings.append(f"Share {share.name} uses a symbolic link; the resolved target was checked against the path policy")
                if not path.exists():
                    if share.create_directory:
                        changes.append({"kind": "directory_created", "name": share.path})
                    else:
                        errors.append(f"Share path does not exist: {share.path}")
                elif not path.is_dir():
                    errors.append(f"Share path is not a directory: {share.path}")
                elif path.stat().st_mode & 0o111 == 0:
                    warnings.append(f"Share path may not be traversable: {share.path}")
                if share.directory_owner or share.directory_group or share.directory_mode:
                    changes.append({"kind": "permissions_changed", "name": share.path})
                account_tokens = [*share.valid_users, *share.write_list, *share.read_list, *share.admin_users]
                for token in account_tokens:
                    account_name = token.removeprefix("@")
                    try:
                        if token.startswith("@"):
                            grp.getgrnam(account_name)
                        else:
                            account = pwd.getpwnam(account_name)
                            if account.pw_uid < get_config().security.system_uid_threshold:
                                errors.append(f"System account cannot be granted direct share access: {account_name}")
                    except KeyError:
                        errors.append(f"Samba access account does not exist: {token}")
                for group_name in share.valid_groups:
                    try:
                        grp.getgrnam(group_name)
                    except KeyError:
                        errors.append(f"Samba access group does not exist: {group_name}")
                if share.guest_ok and not share.read_only:
                    warnings.append(f"Share {share.name} allows anonymous write access")
            if model.global_options.get("bind interfaces only", "no").lower() != "yes" or not model.global_options.get("interfaces"):
                warnings.append("Samba is not restricted to an explicit interface list")
        except Exception as error:  # validation must return structured feedback
            detail = getattr(error, "detail", None)
            errors.append(str(detail or error))
        confirmations = ["smb1"] if any("SMB1" in warning for warning in warnings) else []
        return ModuleValidationResult(ok=not errors, errors=errors, warnings=list(dict.fromkeys(warnings)), changes=changes, generated_config=generated, validator_output=validator_output, confirmations_required=confirmations)

    def sessions(self) -> list[dict[str, Any]]:
        executable = shutil.which("smbstatus")
        if not executable:
            return []
        result = subprocess.run([executable, "--json"], capture_output=True, text=True, timeout=12, check=False, shell=False)
        if result.returncode == 0:
            parsed = parse_smbstatus_json(result.stdout)
            if parsed or result.stdout.strip().startswith("{"):
                return parsed
        fallback = subprocess.run([executable, "-S"], capture_output=True, text=True, timeout=12, check=False, shell=False)
        return parse_smbstatus_text(fallback.stdout) if fallback.returncode == 0 else []

    def test_share_access(self, share_name: str) -> dict[str, Any]:
        config = apps.read_samba_config()
        share = next((item for item in config.shares if item.name.casefold() == share_name.casefold()), None)
        if share is None:
            api_error(404, "SHARE_NOT_FOUND", "Samba share was not found")
        warnings: list[str] = []
        errors: list[str] = []
        try:
            resolved = apps.validate_share_path(self.actor, share)
            exists = resolved.exists()
            is_directory = resolved.is_dir()
            if not exists:
                errors.append("Share path does not exist")
            elif not is_directory:
                errors.append("Share path is not a directory")
            if Path(share.path).is_symlink():
                warnings.append("Share path is a symbolic link")
            mode = resolved.stat().st_mode & 0o777 if exists else None
            if mode is not None and mode & 0o111 == 0:
                warnings.append("Directory has no traversal bit")
            return {
                "share": share.name,
                "path": share.path,
                "resolved_path": str(resolved),
                "exists": exists,
                "is_directory": is_directory,
                "read_only": share.read_only,
                "mode": f"{mode:04o}" if mode is not None else None,
                "ok": not errors,
                "warnings": warnings,
                "errors": errors,
            }
        except Exception as error:
            detail = getattr(error, "detail", None)
            return {"share": share.name, "path": share.path, "resolved_path": "", "exists": False, "is_directory": False, "read_only": share.read_only, "mode": None, "ok": False, "warnings": warnings, "errors": [str(detail or error)]}

    def users(self) -> list[dict[str, Any]]:
        base = apps.samba_users_payload()
        groups_by_user: dict[str, list[str]] = {}
        for definition in grp.getgrall():
            for username in definition.gr_mem:
                groups_by_user.setdefault(username, []).append(definition.gr_name)
        return [{**item, "status": "enabled" if item["samba_enabled"] else "not_enrolled", "groups": sorted(groups_by_user.get(item["username"], [])), "last_changed": None} for item in base if not item["system"]]

    @staticmethod
    def manage_user(action: str, username: str, password: str | None = None) -> None:
        if action not in {"add", "password", "enable", "disable", "remove"}:
            api_error(400, "INVALID_USER_ACTION", "Unsupported Samba user action")
        try:
            account = pwd.getpwnam(username)
        except KeyError:
            api_error(404, "USER_NOT_FOUND", "Linux user does not exist")
        if account.pw_uid < get_config().security.system_uid_threshold:
            api_error(403, "SYSTEM_USER_PROTECTED", "System users cannot be enrolled in Samba")
        executable = shutil.which("smbpasswd")
        if not executable:
            api_error(503, "SMBPASSWD_UNAVAILABLE", "smbpasswd is not installed")
        if action in {"add", "password"}:
            if not password or len(password) > 1024 or any(char in password for char in "\r\n\x00"):
                api_error(400, "INVALID_PASSWORD", "Invalid SMB password")
            args = [executable, "-s", "-a", username]
            result = subprocess.run(args, input=f"{password}\n{password}\n", capture_output=True, text=True, timeout=20, check=False, shell=False)
        else:
            flag = {"enable": "-e", "disable": "-d", "remove": "-x"}[action]
            result = subprocess.run([executable, flag, username], capture_output=True, text=True, timeout=20, check=False, shell=False)
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or "smbpasswd failed"))

    def get_log_sources(self) -> list[dict[str, str]]:
        sources = [{"id": "journal:smbd", "label": "smbd"}, {"id": "journal:nmbd", "label": "nmbd"}, {"id": "journal:winbind", "label": "winbind"}]
        for source_id, label, path in (
            ("file:log.smbd", "log.smbd", Path("/var/log/samba/log.smbd")),
            ("file:log.nmbd", "log.nmbd", Path("/var/log/samba/log.nmbd")),
            ("file:log.winbindd", "log.winbindd", Path("/var/log/samba/log.winbindd")),
        ):
            if path.is_file():
                sources.append({"id": source_id, "label": label})
        return sources

    def get_logs(self, source: str, lines: int = 200, search: str = "", level: str = "") -> dict[str, Any]:
        files = {
            "file:log.smbd": Path("/var/log/samba/log.smbd"),
            "file:log.nmbd": Path("/var/log/samba/log.nmbd"),
            "file:log.winbindd": Path("/var/log/samba/log.winbindd"),
        }
        if source not in files:
            return super().get_logs(source, lines, search, level)
        path = files[source]
        if not path.is_file() or source not in {item["id"] for item in self.get_log_sources()}:
            api_error(400, "INVALID_LOG_SOURCE", "Unsupported module log source")
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 512 * 1024))
            output = handle.read(512 * 1024).decode("utf-8", errors="replace").splitlines()
        needle = search.strip().lower()
        level_needle = level.strip().lower()
        cleaned = [redact(item) for item in output]
        if needle:
            cleaned = [item for item in cleaned if needle in item.lower()]
        if level_needle:
            cleaned = [item for item in cleaned if level_needle in item.lower()]
        limit = min(max(lines, 1), 1000)
        return {"source": source, "lines": cleaned[-limit:], "truncated": len(cleaned) > limit}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        config = apps.read_samba_config()
        checks: list[ModuleDiagnostic] = []
        version = self._version()
        def add(ok: bool, title: str, good: str, bad: str, action: str = "") -> None:
            checks.append(ModuleDiagnostic(status="ok" if ok else "warning", title=title, description=good if ok else bad, details="", severity="ok" if ok else "warning", recommended_action="" if ok else action))
        add(status.installed, "Samba packages", "Samba is installed", "Samba packages are missing", "Install Samba")
        add(bool(version), "Samba version", f"Detected {version or ''}".strip(), "Could not determine the Samba version", "Verify the smbd executable")
        add(shutil.which("testparm") is not None, "Configuration validator", "testparm is available", "testparm is unavailable", "Install Samba tools")
        add(bool(status.configuration_valid), "smb.conf", "Configuration is valid", "Configuration validation failed", "Review the generated configuration")
        add(status.service_state == "active", "Samba services", "At least one Samba service is active", "Samba services are inactive", "Start required services")
        add(all(not item.get("required") or item.get("enabled") for item in status.services.values()), "Service autostart", "Required services start automatically", "A required service is disabled at boot", "Enable required Samba services")
        for port, open_state in apps.samba_port_status().items():
            add(open_state, f"Port {port}", "Port is accepting connections", "Port is not accepting connections", "Review service and firewall status")
        for share in config.shares:
            path = Path(share.path)
            exists = path.is_dir()
            add(exists, f"Share path: {share.name}", "Share directory exists", "Share directory is unavailable", "Create or correct the directory")
            if exists:
                mode = path.stat().st_mode & 0o777
                add(bool(mode & 0o111), f"Directory access: {share.name}", f"Directory mode is {mode:04o}", "Directory cannot be traversed", "Review directory permissions")
                free = shutil.disk_usage(path).free
                add(free >= 100 * 1024 * 1024, f"Free space: {share.name}", f"{free // (1024 * 1024)} MiB available", "Less than 100 MiB is available", "Free disk space")
            if path.is_symlink():
                checks.append(ModuleDiagnostic(status="warning", title=f"Symbolic link: {share.name}", description="The share path is a symbolic link", details=f"{path} -> {path.resolve(strict=False)}", severity="warning", recommended_action="Confirm that the resolved target is intentional and remains inside an allowed root"))
            if share.guest_ok and not share.read_only:
                checks.append(ModuleDiagnostic(status="critical", title=f"Anonymous write: {share.name}", description="Guest users can write to this share", details=share.path, severity="critical", recommended_action="Disable guest access or make the share read-only"))
        names = [item.name.casefold() for item in config.shares]
        add(len(names) == len(set(names)), "Share names", "Share names are unique", "Conflicting share names were detected", "Rename duplicate shares")
        add(not any(value.lower() in SMB1_VALUES for key, value in config.global_options.items() if key in {"server min protocol", "server max protocol"}), "SMB protocol", "Legacy SMB1 is disabled", "Legacy SMB1 may be enabled", "Require SMB2 or newer")
        restricted_interfaces = config.global_options.get("bind interfaces only", "no").lower() == "yes" and bool(config.global_options.get("interfaces"))
        add(restricted_interfaces, "Network interfaces", "Samba is restricted to configured interfaces", "Samba is not restricted to an explicit interface list", "Configure interfaces and enable bind interfaces only")
        if shutil.which("pdbedit"):
            pdb = subprocess.run([shutil.which("pdbedit") or "pdbedit", "-L"], capture_output=True, text=True, timeout=10, check=False, shell=False)
            if pdb.returncode == 0:
                samba_accounts = {line.split(":", 1)[0] for line in pdb.stdout.splitlines() if ":" in line}
                linux_accounts = {item.pw_name for item in pwd.getpwall()}
                stale = sorted(samba_accounts - linux_accounts)
                add(not stale, "SMB/Linux accounts", "Every Samba account has a Linux account", f"Missing Linux accounts: {', '.join(stale)}", "Remove stale Samba accounts")
        firewall = "ufw" if shutil.which("ufw") else "firewalld" if shutil.which("firewall-cmd") else "unsupported"
        checks.append(ModuleDiagnostic(status="info", title="Firewall", description=f"Detected firewall adapter: {firewall}", details="Ports 137/udp, 138/udp, 139/tcp, 445/tcp", severity="info", recommended_action="Review firewall rules" if firewall == "unsupported" else ""))
        return checks

    def list_backups(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for metadata in self.backup_dir.glob("*.json"):
            try:
                value = json.loads(metadata.read_text(encoding="utf-8"))
                result.append(ModuleBackup.model_validate(value).model_dump(mode="json"))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        backup_id = uuid4().hex
        managed = apps.SAMBA_ALGEN_CONF.read_bytes() if apps.SAMBA_ALGEN_CONF.exists() else apps.render_smb_conf(apps.read_samba_config()).encode("utf-8")
        main = apps.SAMBA_CONF.read_bytes() if apps.SAMBA_CONF.exists() else None
        digest = hashlib.sha256(b"WEBNAS-SAMBA-BACKUP-v1\0")
        digest.update(main if main is not None else b"<absent>")
        digest.update(b"\0managed\0")
        digest.update(managed)
        checksum = digest.hexdigest()
        managed_path = self.backup_dir / f"{backup_id}.managed.conf"
        main_path = self.backup_dir / f"{backup_id}.main.conf"
        metadata_path = self.backup_dir / f"{backup_id}.json"
        self._atomic_write(managed_path, managed)
        files = ["algen-shares.conf"]
        if main is not None:
            self._atomic_write(main_path, main)
            files.append("smb.conf")
        else:
            files.append("smb.conf.absent")
        backup = ModuleBackup(id=backup_id, module_id="samba", created_at=time.time(), created_by=actor, description=description.strip()[:200], automatic=automatic, checksum=checksum, package_version=self._version() or "", size=len(managed) + len(main or b""), files=files)
        self._atomic_write(metadata_path, backup.model_dump_json(indent=2).encode("utf-8"))
        for path in (managed_path, main_path, metadata_path):
            if not path.exists():
                continue
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        if automatic:
            automatic_backups = [item for item in self.list_backups() if item["automatic"]]
            for old in automatic_backups[20:]:
                self.delete_backup(old["id"])
        return backup.model_dump(mode="json")

    def _backup_files(self, backup_id: str) -> tuple[bytes | None, bytes, bool]:
        if not BACKUP_ID_RE.fullmatch(backup_id):
            api_error(400, "INVALID_BACKUP_ID", "Invalid backup identifier")
        metadata = self.backup_dir / f"{backup_id}.json"
        managed_path = self.backup_dir / f"{backup_id}.managed.conf"
        main_path = self.backup_dir / f"{backup_id}.main.conf"
        legacy_path = self.backup_dir / f"{backup_id}.conf"
        if not metadata.is_file() or not managed_path.is_file() and not legacy_path.is_file():
            api_error(404, "BACKUP_NOT_FOUND", "Module backup not found")
        value = ModuleBackup.model_validate_json(metadata.read_text(encoding="utf-8"))
        if legacy_path.is_file():
            managed = legacy_path.read_bytes()
            if hashlib.sha256(managed).hexdigest() != value.checksum:
                api_error(409, "BACKUP_CHECKSUM_MISMATCH", "Backup checksum verification failed")
            return None, managed, False
        managed = managed_path.read_bytes()
        restore_main = "smb.conf" in value.files or "smb.conf.absent" in value.files
        main = main_path.read_bytes() if "smb.conf" in value.files and main_path.is_file() else None
        digest = hashlib.sha256(b"WEBNAS-SAMBA-BACKUP-v1\0")
        digest.update(main if main is not None else b"<absent>")
        digest.update(b"\0managed\0")
        digest.update(managed)
        if digest.hexdigest() != value.checksum:
            api_error(409, "BACKUP_CHECKSUM_MISMATCH", "Backup checksum verification failed")
        return main, managed, restore_main

    def _backup_content(self, backup_id: str) -> bytes:
        return self._backup_files(backup_id)[1]

    def delete_backup(self, backup_id: str) -> None:
        self._backup_files(backup_id)
        for suffix in (".conf", ".managed.conf", ".main.conf", ".json"):
            path = self.backup_dir / f"{backup_id}{suffix}"
            if path.exists():
                path.unlink()

    def cleanup_after_uninstall(self, actor: str, remove_config: bool) -> dict[str, Any]:
        if not remove_config:
            return {"managed_config_removed": False}
        apps.remove_smb_conf_include()
        if apps.SAMBA_ALGEN_CONF.exists():
            apps.SAMBA_ALGEN_CONF.unlink()
        state = apps.read_state("samba")
        state.update({"configured": False, "config": {"shares": [], "global_options": {}}})
        state.setdefault("changes", []).append({"ts": time.time(), "actor": actor, "action": "remove_managed_config"})
        apps.write_state("samba", state)
        return {"managed_config_removed": True, "shared_data_removed": False}

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _reload_and_verify(self, log: LogCallback) -> None:
        if shutil.which("systemctl") and shutil.which("smbd"):
            result = self._systemctl("smbd", "reload")
            log("stdout" if result.returncode == 0 else "stderr", result.stdout.strip() or result.stderr.strip() or "Reload smbd")
            if result.returncode != 0:
                raise RuntimeError("Samba reload failed")
            state = self._systemctl("smbd", "is-active")
            if state.returncode != 0:
                raise RuntimeError("Samba is not active after reload")

    def _restore_files(self, main: bytes | None, managed: bytes, restore_main: bool, log: LogCallback) -> apps.SambaConfig:
        validation = apps.testparm_config(managed.decode("utf-8", errors="replace"))
        if not validation.get("ok"):
            raise RuntimeError("Backup failed testparm validation")
        self._atomic_write(apps.SAMBA_ALGEN_CONF, managed)
        if restore_main:
            if main is None:
                if apps.SAMBA_CONF.exists():
                    apps.SAMBA_CONF.unlink()
            else:
                self._atomic_write(apps.SAMBA_CONF, main)
        effective = apps.SAMBA_CONF.read_text(encoding="utf-8", errors="replace") if apps.SAMBA_CONF.exists() else managed.decode("utf-8", errors="replace")
        effective_validation = apps.testparm_config(effective)
        if not effective_validation.get("ok"):
            raise RuntimeError("Restored effective Samba configuration failed testparm validation")
        self._reload_and_verify(log)
        return parse_smb_conf(managed.decode("utf-8", errors="replace"))

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action == PackageAction.apply:
            progress(5, "Validate configuration")
            config = apps.SambaConfig.model_validate(payload.get("config") or {})
            validation = self.validate_config(config.model_dump())
            if not validation.ok:
                raise RuntimeError("; ".join(validation.errors))
            if cancelled():
                raise InterruptedError("Configuration apply cancelled")
            progress(20, "Create configuration backup")
            backup = self.create_backup(actor, "Automatic backup before configuration change", True)
            old_main, old_managed, restore_main = self._backup_files(backup["id"])
            try:
                progress(40, "Write candidate configuration")
                for share in config.shares:
                    resolved = apps.validate_share_path(actor, share)
                    apps._prepare_share_directory(share, resolved)
                apps._ensure_smb_conf_include()
                self._atomic_write(apps.SAMBA_ALGEN_CONF, validation.generated_config.encode("utf-8"))
                progress(65, "Reload Samba service")
                self._reload_and_verify(log)
                progress(82, "Verify applied configuration")
                effective = apps.SAMBA_CONF if apps.SAMBA_CONF.exists() else apps.SAMBA_ALGEN_CONF
                post = apps.testparm_config(effective.read_text(encoding="utf-8", errors="replace"))
                if not post.get("ok"):
                    raise RuntimeError("Applied configuration failed post-write validation")
                state = apps.read_state("samba")
                state.update({"configured": True, "config": config.model_dump(), "last_validation": post, "last_backup": backup["id"]})
                state.setdefault("changes", []).append({"ts": time.time(), "actor": actor, "action": "apply_config"})
                apps.write_state("samba", state)
                progress(96, "Configuration applied")
                return {"validation": validation.model_dump(mode="json"), "backup": backup, "rolled_back": False}
            except Exception:
                progress(88, "Restore previous configuration")
                self._restore_files(old_main, old_managed, restore_main, log)
                log("stderr", "Configuration was rolled back automatically")
                raise
        if action == PackageAction.restore:
            progress(15, "Verify backup")
            main, managed, restore_main = self._backup_files(str(payload.get("backup_id") or ""))
            current = self.create_backup(actor, "Automatic backup before restore", True)
            try:
                progress(50, "Restore configuration")
                restored = self._restore_files(main, managed, restore_main, log)
                progress(90, "Verify restored configuration")
                state = apps.read_state("samba")
                state.update({"configured": True, "config": restored.model_dump(), "last_backup": payload["backup_id"]})
                state.setdefault("changes", []).append({"ts": time.time(), "actor": actor, "action": "restore_backup"})
                apps.write_state("samba", state)
                return {"restored": payload["backup_id"], "safety_backup": current}
            except Exception:
                safety_main, safety_managed, safety_restore_main = self._backup_files(current["id"])
                self._restore_files(safety_main, safety_managed, safety_restore_main, log)
                raise
        return super().execute_operation(action, payload, actor, log, progress, cancelled)
