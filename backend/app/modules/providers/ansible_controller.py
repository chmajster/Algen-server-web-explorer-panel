from __future__ import annotations

import os
import re
import signal
import shlex
import shutil
import sqlite3
import subprocess
import time
from typing import Any

from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus, ModuleValidationResult, PackageAction, api_error
from ..ansible_controller.awx import AwxClient
from ..ansible_controller.backup import create_backup, delete_backup as remove_backup, list_backups, restore_backup
from ..ansible_controller.models import MANAGED_SSH_USERNAME, PROTECTED_MANAGED_USERNAMES, AwxSettingsInput, CredentialInput, CredentialType, HostInput, NetworkScanInput
from ..ansible_controller.network import build_nmap_args, parse_nmap_xml, scan_addresses
from ..ansible_controller.repository import repository
from ..ansible_controller.runner import controller_identity, demote_preexec, execute_ad_hoc, execute_template, execution_directory, run_remote_user_setup
from ..ansible_controller.security import atomic_private_write, redact_text
from .base import CancelCallback, LogCallback, ModuleProvider, ProgressCallback


def _run_cancellable(
    args: list[str],
    *,
    timeout: int,
    cancelled: CancelCallback,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        start_new_session=True,
        cwd=cwd,
        env=env,
        preexec_fn=demote_preexec(uid, gid) if os.name != "nt" and uid is not None and gid is not None else None,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancelled():
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGINT)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
            process.communicate()
            raise InterruptedError("Network scan cancelled")
        if time.monotonic() >= deadline:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            process.communicate()
            raise RuntimeError("Network scan timed out")
        try:
            stdout, stderr = process.communicate(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            continue
    return subprocess.CompletedProcess(args, int(process.returncode or 0), stdout, stderr)


def _generate_host_key(store: Any, host_id: str) -> tuple[str, str]:
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise RuntimeError("ssh-keygen is unavailable")
    with execution_directory(store, "host-keygen") as directory:
        key_path = directory / "id_ed25519"
        result = subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", f"webnas-ansible:{host_id}", "-f", str(key_path)], capture_output=True, text=True, timeout=30, check=False, shell=False)
        if result.returncode != 0 or not key_path.is_file() or not key_path.with_suffix(".pub").is_file():
            raise RuntimeError("host-specific SSH key generation failed")
        return key_path.read_text(encoding="utf-8"), key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()


class AnsibleControllerProvider(ModuleProvider):
    def __init__(self, actor: str = "root") -> None:
        super().__init__("ansible-controller")
        self.actor = actor
        self.store = repository()

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        installed = status.installed
        ansible = shutil.which("ansible")
        version = ""
        if ansible:
            result = subprocess.run([ansible, "--version"], capture_output=True, text=True, timeout=10, check=False, shell=False)
            version = result.stdout.splitlines()[0][:200] if result.returncode == 0 else ""
        metrics = self.store.dashboard()
        account_ok = False
        if os.name != "nt":
            try:
                import pwd

                account_ok = pwd.getpwnam("webnas-ansible").pw_uid != 0
            except KeyError:
                account_ok = False
        health = ModuleHealth.not_installed if not installed else ModuleHealth.healthy if ansible and account_ok else ModuleHealth.degraded
        return status.model_copy(update={
            "service_state": "ready" if health == ModuleHealth.healthy else "degraded" if installed else "not_installed",
            "health": health,
            "health_message": "Controller is ready" if health == ModuleHealth.healthy else "Controller account or ansible-core is unavailable" if installed else "Module is not installed",
            "metrics": {**metrics, "ansible_version": version, "controller_user_ready": account_ok},
        })

    def get_config(self) -> dict[str, Any]:
        self.assert_capability("configure")
        value = self.store.setting("controller")
        awx = dict(value.get("awx") or {})
        awx.pop("token", None)
        if awx:
            awx["token_configured"] = bool(awx.get("credential_id"))
        return {
            "allowed_networks": list(value.get("allowed_networks") or []),
            "max_scan_addresses": min(int(value.get("max_scan_addresses") or 4096), 4096),
            "default_concurrency_policy": value.get("default_concurrency_policy") or "same_hosts",
            "managed_username": value.get("managed_username") or MANAGED_SSH_USERNAME,
            "managed_sudo_profile": value.get("managed_sudo_profile") or "none",
            "managed_shell": value.get("managed_shell") or "/bin/bash",
            "managed_comment": value.get("managed_comment") if isinstance(value.get("managed_comment"), str) else "Algen Ansible automation",
            "managed_authorized_keys_mode": "exclusive",
            "managed_key_rotation_days": min(max(int(value.get("managed_key_rotation_days") if value.get("managed_key_rotation_days") is not None else 90), 0), 365),
            "awx": awx,
        }

    def validate_config(self, config: dict[str, Any]) -> ModuleValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        allowed = config.get("allowed_networks") or []
        if not isinstance(allowed, list) or len(allowed) > 100:
            errors.append("allowed_networks must contain at most 100 CIDR values")
        else:
            import ipaddress

            for raw in allowed:
                try:
                    network = ipaddress.ip_network(str(raw), strict=False)
                    if network.prefixlen == 0:
                        raise ValueError
                except ValueError:
                    errors.append(f"Invalid allowed network: {str(raw)[:64]}")
        if (config.get("default_concurrency_policy") or "same_hosts") not in {"parallel", "same_hosts", "template", "single"}:
            errors.append("invalid default concurrency policy")
        managed_username = str(config.get("managed_username") or MANAGED_SSH_USERNAME)
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]", managed_username) or managed_username.casefold() in PROTECTED_MANAGED_USERNAMES:
            errors.append("invalid managed account username")
        if (config.get("managed_sudo_profile") or "none") not in {"none", "nopasswd"}:
            errors.append("invalid managed account sudo profile")
        if (config.get("managed_shell") or "/bin/bash") not in {"/bin/bash", "/bin/sh"}:
            errors.append("invalid managed account shell")
        comment = config.get("managed_comment") if isinstance(config.get("managed_comment"), str) else "Algen Ansible automation"
        if not isinstance(comment, str) or len(comment) > 100 or any(character in comment for character in ":\r\n"):
            errors.append("invalid managed account comment")
        if (config.get("managed_authorized_keys_mode") or "exclusive") != "exclusive":
            errors.append("invalid managed account authorized keys mode")
        try:
            rotation_days = int(config.get("managed_key_rotation_days") if config.get("managed_key_rotation_days") is not None else 90)
            if not 0 <= rotation_days <= 365:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("invalid managed host key rotation interval")
        if isinstance(config.get("awx"), dict) and config["awx"].get("url"):
            try:
                AwxSettingsInput.model_validate(config["awx"])
            except ValueError as error:
                errors.append(str(error))
            if config["awx"].get("verify_tls") is False:
                warnings.append("TLS verification is disabled for external AWX")
        return ModuleValidationResult(ok=not errors, errors=errors, warnings=warnings, changes=[], confirmations_required=["awx_tls_disabled"] if any("TLS" in item for item in warnings) else [])

    def save_config(self, config: dict[str, Any], actor: str) -> dict[str, Any]:
        validation = self.validate_config(config)
        if not validation.ok:
            api_error(422, "CONFIG_VALIDATION_FAILED", "Controller configuration is invalid", errors=validation.errors)
        return self.store.save_setting("controller", config, actor)

    def get_log_sources(self) -> list[dict[str, str]]:
        sources = [{"id": "executions", "label": "Recent executions"}]
        sources.extend({"id": f"execution:{item['id']}", "label": f"Execution {item['id'][:12]}"} for item in self.store.executions()[:50])
        return sources

    def get_logs(self, source: str, lines: int = 200, search: str = "", level: str = "") -> dict[str, Any]:
        allowed = {item["id"] for item in self.get_log_sources()}
        if source not in allowed:
            api_error(400, "INVALID_LOG_SOURCE", "Unsupported controller log source")
        output: list[str] = []
        if source == "executions":
            output = [f"{item['created_at']} {item['status']} {item['id']} template={item.get('template_id') or '-'}" for item in self.store.executions()[:lines]]
        else:
            item = self.store.execution(source.split(":", 1)[1])
            if item:
                output = (str(item.get("stdout") or "") + "\n" + str(item.get("stderr") or "")).splitlines()
        if search:
            output = [line for line in output if search.casefold() in line.casefold()]
        if level:
            output = [line for line in output if level.casefold() in line.casefold()]
        return {"source": source, "lines": [redact_text(line) for line in output[-min(lines, 1000):]], "truncated": len(output) > lines}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        checks: list[ModuleDiagnostic] = []
        version_args = {
            "ansible": ["--version"],
            "ansible-playbook": ["--version"],
            "ansible-inventory": ["--version"],
            "ssh": ["-V"],
            "nmap": ["--version"],
            "git": ["--version"],
        }
        for executable, arguments in version_args.items():
            path = shutil.which(executable)
            details = ""
            if path:
                result = subprocess.run([path, *arguments], capture_output=True, text=True, timeout=10, check=False, shell=False)
                details = redact_text(result.stdout or result.stderr).splitlines()[0][:500] if result.stdout or result.stderr else path
            available = bool(path)
            checks.append(ModuleDiagnostic(status="ok" if available else "critical", title=executable, description="Executable is available" if available else "Executable is missing", details=details, severity="ok" if available else "critical", recommended_action="Install or update the module" if not available else ""))
        try:
            if os.name != "nt":
                import pwd

                account = pwd.getpwnam("webnas-ansible")
            else:
                account = None
            safe_account = bool(account and account.pw_uid != 0 and account.pw_shell in {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"})
            details = f"uid={account.pw_uid} gid={account.pw_gid}" if account else "not available on this platform"
        except KeyError:
            safe_account, details = False, "account is missing"
        checks.append(ModuleDiagnostic(status="ok" if safe_account else "critical", title="Controller account", description="webnas-ansible is isolated" if safe_account else "webnas-ansible is missing or unsafe", details=details, severity="ok" if safe_account else "critical", recommended_action="Reinstall the module" if not safe_account else ""))
        mode_ok = self.store.root.is_dir() and not (self.store.root.stat().st_mode & 0o077)
        checks.append(ModuleDiagnostic(status="ok" if mode_ok else "critical", title="Data directory", description="Private permissions are enforced" if mode_ok else "Data directory is accessible to other users", details=str(self.store.root), severity="ok" if mode_ok else "critical", recommended_action="Set directory mode to 0700" if not mode_ok else ""))
        key_paths = [self.store.root / "home" / ".ssh" / "id_ed25519", self.store.cipher.key_path]
        unsafe_keys = [str(path) for path in key_paths if path.exists() and path.stat().st_mode & 0o077]
        missing_keys = [str(path) for path in key_paths if not path.is_file()]
        keys_ok = not unsafe_keys and not missing_keys
        checks.append(ModuleDiagnostic(status="ok" if keys_ok else "critical", title="Private keys", description="Controller and encryption keys are private" if keys_ok else "A private key is missing or has an unsafe mode", details=redact_text({"missing": missing_keys, "unsafe": unsafe_keys}), severity="ok" if keys_ok else "critical", recommended_action="Reinstall the module or set key modes to 0600" if not keys_ok else ""))
        config_path = self.store.root / "config" / "ansible.cfg"
        try:
            config_text = config_path.read_text(encoding="utf-8")
        except OSError:
            config_text = ""
        config_ok = bool(config_text) and "host_key_checking = True" in config_text and "host_key_checking = False" not in config_text
        checks.append(ModuleDiagnostic(status="ok" if config_ok else "critical", title="ansible.cfg", description="Host-key checking is enabled" if config_ok else "Managed Ansible configuration is missing or unsafe", details=str(config_path), severity="ok" if config_ok else "critical", recommended_action="Reinstall or update the module" if not config_ok else ""))
        try:
            with self.store.connect() as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error as error:
            integrity = str(error)
            schema_version = -1
        checks.append(ModuleDiagnostic(status="ok" if integrity == "ok" else "critical", title="Controller database", description="SQLite integrity check passed" if integrity == "ok" else "SQLite integrity check failed", details=redact_text(integrity), severity="ok" if integrity == "ok" else "critical", recommended_action="Restore a verified backup" if integrity != "ok" else ""))
        checks.append(ModuleDiagnostic(status="ok" if schema_version == 1 else "critical", title="Database migration", description="Controller schema is current" if schema_version == 1 else "Controller schema version is unexpected", details=f"user_version={schema_version}", severity="ok" if schema_version == 1 else "critical", recommended_action="Update the module" if schema_version != 1 else ""))
        probe = self.store.root / ".diagnostic-write"
        try:
            atomic_private_write(probe, b"diagnostic")
            writable = probe.is_file()
        except OSError:
            writable = False
        finally:
            probe.unlink(missing_ok=True)
        checks.append(ModuleDiagnostic(status="ok" if writable else "critical", title="Data write", description="Private data directory is writable" if writable else "Private data directory is not writable", severity="ok" if writable else "critical"))
        isolation_ok = safe_account and (os.name == "nt" or all(hasattr(os, name) for name in ("setgroups", "setgid", "setuid")))
        checks.append(ModuleDiagnostic(status="ok" if isolation_ok else "critical", title="Process isolation", description="UID/GID demotion is available" if isolation_ok else "UID/GID demotion cannot be guaranteed", severity="ok" if isolation_ok else "critical"))
        credential_errors = 0
        for item in self.store.credentials():
            try:
                self.store.credential_secret(str(item["id"]))
            except (KeyError, ValueError):
                credential_errors += 1
        checks.append(ModuleDiagnostic(status="ok" if credential_errors == 0 else "critical", title="Credential encryption", description="All active credential envelopes authenticate" if credential_errors == 0 else "One or more credential envelopes are invalid", details=f"invalid={credential_errors}", severity="ok" if credential_errors == 0 else "critical"))
        leftovers = len(list((self.store.root / "runs").glob("run-*"))) if (self.store.root / "runs").exists() else 0
        checks.append(ModuleDiagnostic(status="ok" if leftovers == 0 else "warning", title="Temporary executions", description="No temporary execution directories remain" if leftovers == 0 else f"{leftovers} temporary directories remain", severity="ok" if leftovers == 0 else "warning", recommended_action="Review orphaned executions" if leftovers else ""))
        known_keys = len(self.store._list("known_host_keys", where="active=1 AND status='accepted'", limit=10_000))
        checks.append(ModuleDiagnostic(status="ok", title="SSH known hosts", description="Accepted fingerprints are stored privately", details=f"accepted={known_keys}", severity="ok"))
        failed_jobs = [item for item in self.store.executions() if item.get("status") == "failed"]
        checks.append(ModuleDiagnostic(status="warning" if failed_jobs else "ok", title="Recent execution errors", description=f"{len(failed_jobs)} failed executions retained" if failed_jobs else "No failed executions are retained", details=redact_text([item.get("stderr", "")[-200:] for item in failed_jobs[:5]]), severity="warning" if failed_jobs else "ok"))
        schedules = self.store.schedules()
        checks.append(ModuleDiagnostic(status="ok", title="Persistent scheduler", description="Schedule records are readable", details=f"active={sum(1 for item in schedules if item.get('active'))} total={len(schedules)}", severity="ok"))
        awx = self.get_config().get("awx") or {}
        checks.append(ModuleDiagnostic(status="info", title="External AWX", description="Configured" if awx.get("url") else "Not configured", severity="info"))
        return checks

    def list_backups(self) -> list[dict[str, Any]]:
        return list_backups(self.store)

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        return create_backup(self.store, actor, description, include_credentials=False) | {"automatic": automatic}

    def delete_backup(self, backup_id: str) -> None:
        remove_backup(self.store, backup_id, self.actor)

    def cleanup_after_uninstall(self, actor: str, remove_config: bool) -> dict[str, Any]:
        managed_hosts = [
            {"id": host["id"], "name": host["name"], "address": host["address"], "managed_username": "algen-ansible"}
            for host in self.store.list_hosts()
            if host.get("managed_user_created")
        ]
        removed = False
        if remove_config:
            config_path = self.store.root / "config" / "ansible.cfg"
            config_path.unlink(missing_ok=True)
            with self.store._lock, self.store.connect() as connection:
                connection.execute(
                    "UPDATE controller_settings SET config_json='{}',active=0,updated_at=?,updated_by=? WHERE key='controller'",
                    (time.time(), actor),
                )
            removed = True
        return {
            "managed_config_removed": removed,
            "remote_accounts_preserved": managed_hosts,
            "remote_accounts_removed": False,
        }

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation == "network_scan":
            scan_id = str(payload.get("scan_id") or "")
            scan = self.store.scan(scan_id)
            if not scan:
                raise KeyError("network scan not found")
            request = NetworkScanInput.model_validate(scan["request"])
            config = self.get_config()
            addresses = scan_addresses(request, config.get("allowed_networks") or [], min(int(config.get("max_scan_addresses") or 4096), 4096))
            executable = shutil.which("nmap")
            if not executable:
                raise RuntimeError("nmap is unavailable")
            args = build_nmap_args(request, addresses, executable)
            progress(10, f"Scan {len(addresses)} approved addresses")
            uid, gid, _home = controller_identity()
            try:
                result = _run_cancellable(args, timeout=min(900, max(30, int(len(addresses) * request.timeout_seconds))), cancelled=cancelled, uid=uid, gid=gid)
            except InterruptedError:
                self.store.cancel_scan(scan_id, actor)
                raise
            except Exception as error:
                self.store.complete_scan(scan_id, actor, [], redact_text(error))
                raise
            if result.returncode != 0:
                self.store.complete_scan(scan_id, actor, [], redact_text(result.stderr))
                raise RuntimeError("nmap network scan failed")
            hosts = parse_nmap_xml(result.stdout, request.port, request.reverse_dns)
            self.store.complete_scan(scan_id, actor, hosts)
            progress(100, f"Discovered {len(hosts)} SSH endpoints")
            return {"scan_id": scan_id, "discovered": len(hosts), "hosts": hosts}
        if operation == "launch":
            execution = self.store.execution(str(payload.get("execution_id") or ""))
            template = self.store._get("job_templates", str((execution or {}).get("template_id") or ""))
            project = self.store._get("projects", str((template or {}).get("project_id") or ""))
            if project and project.get("source_type") == "git" and (bool((template or {}).get("sync_before_run")) or bool(project.get("sync_before_run"))):
                progress(5, "Synchronize Git project before execution")
                self.manage("sync_project", {"project_id": project["id"]}, actor, log, progress, cancelled)
            return execute_template(self.store, str(payload.get("execution_id") or ""), actor, log, progress, cancelled)
        if operation == "retry":
            return execute_template(self.store, str(payload.get("execution_id") or ""), actor, log, progress, cancelled)
        if operation == "gather_facts":
            return execute_ad_hoc(self.store, str(payload.get("host_id") or ""), actor, log, progress, cancelled, facts=not bool(payload.get("test_only")))
        if operation in {"onboard_host", "rotate_host_key"}:
            host_id = str(payload.get("host_id") or "")
            host = self.store.host(host_id)
            if not host:
                raise KeyError("host not found")
            if not self.store.known_key(str(host["address"]), int(host["port"])):
                raise RuntimeError("SSH host key is not accepted")
            progress(10, "Verify accepted SSH host fingerprint")
            rotating = operation == "rotate_host_key"
            credential_id = str(host.get("credential_id") or "") if rotating else str(payload.get("credential_id") or host.get("credential_id") or "")
            managed_username = str(payload.get("managed_username") or MANAGED_SSH_USERNAME)
            private_key_value, public_key_value = _generate_host_key(self.store, host_id)
            run_remote_user_setup(
                self.store,
                host,
                credential_id,
                str(host.get("ssh_user") or managed_username) if rotating else str(payload.get("initial_username") or "root"),
                managed_username,
                "none" if rotating else str(payload.get("sudo_profile") or "none"),
                str(payload.get("sudoers_policy") or ""),
                str(payload.get("managed_shell") or "/bin/bash"),
                str(payload.get("managed_comment") or "Algen Ansible automation"),
                "exclusive",
                public_key_value,
                log,
            )
            existing = next((item for item in self.store.credentials() if item["id"] == host.get("credential_id") and str(item.get("description") or "").startswith(f"managed-host:{host_id}")), None)
            credential_payload = CredentialInput(name=f"Host key - {host['name']} - {host_id[:8]}", type=CredentialType.ssh_private_key, username=managed_username, secret=private_key_value, description=f"managed-host:{host_id}; unique Ed25519 key")
            managed_credential = self.store.save_credential(credential_payload, actor, existing["id"] if existing else None)
            updated = HostInput.model_validate({
                "name": host["name"], "address": host["address"], "port": host["port"],
                "ssh_user": managed_username, "credential_id": managed_credential["id"],
                "python_interpreter": host["python_interpreter"], "connection_type": host["connection_type"],
                "environment": host["environment"], "location": host["location"], "tags": host.get("tags") or [],
                "variables": host.get("variables") or {}, "active": host["active"],
            })
            self.store.save_host(updated, actor, host_id)
            with self.store._lock, self.store.connect() as connection:
                connection.execute("UPDATE hosts SET managed_user_created=1,updated_at=?,updated_by=? WHERE id=?", (time.time(), actor, host_id))
            progress(65, f"Unique host key installed for {host['name']}")
            result = execute_ad_hoc(self.store, host_id, actor, log, progress, cancelled, facts=True)
            self.store.audit(actor, "host", host_id, "key_rotated" if rotating else "onboard_complete", {"managed_user_created": True, "managed_username": managed_username, "credential_id": managed_credential["id"], "key_scope": "per_host"})
            return result
        if operation == "sync_project":
            project_id = str(payload.get("project_id") or "")
            project = self.store._get("projects", project_id)
            if not project:
                raise KeyError("project not found")
            if project["source_type"] != "git" or not project["repository_url"]:
                raise RuntimeError("project is not configured as a Git source")
            executable = shutil.which("git")
            if not executable:
                raise RuntimeError("git is unavailable")
            target = self.store.root / "projects" / project_id
            target.parent.mkdir(parents=True, exist_ok=True)
            progress(10, "Synchronize fixed Git revision")
            uid, gid, home = controller_identity()
            with execution_directory(self.store, f"git-{project_id}") as directory:
                if os.name != "nt":
                    os.chown(directory, uid, gid)
                git_env = {
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": str(home),
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1",
                }
                credential_id = str(project.get("credential_id") or "")
                if credential_id:
                    credential = self.store.credential_secret(credential_id)
                    if credential["type"] != CredentialType.git_private_key.value:
                        raise RuntimeError("Git SSH synchronization requires a Git private-key credential")
                    if credential.get("passphrase"):
                        raise RuntimeError("passphrase-protected Git keys require an external agent and are not supported")
                    key_path = directory / "git-key"
                    atomic_private_write(key_path, credential["secret"].encode())
                    if os.name != "nt":
                        os.chown(key_path, uid, gid)
                    ssh = shutil.which("ssh")
                    if not ssh:
                        raise RuntimeError("OpenSSH client is unavailable")
                    known_hosts = home / ".ssh" / "known_hosts"
                    git_env["GIT_SSH_COMMAND"] = " ".join(
                        shlex.quote(value)
                        for value in (
                            ssh,
                            "-i",
                            str(key_path),
                            "-o",
                            "IdentitiesOnly=yes",
                            "-o",
                            "StrictHostKeyChecking=yes",
                            "-o",
                            f"UserKnownHostsFile={known_hosts}",
                        )
                    )
                if not (target / ".git").is_dir():
                    result = _run_cancellable(
                        [executable, "clone", "--depth", "1", "--branch", str(project["revision"]), "--", str(project["repository_url"]), str(target)],
                        timeout=600,
                        cancelled=cancelled,
                        cwd=directory,
                        env=git_env,
                        uid=uid,
                        gid=gid,
                    )
                else:
                    result = _run_cancellable(
                        [executable, "-C", str(target), "fetch", "--depth", "1", "origin", str(project["revision"])],
                        timeout=600,
                        cancelled=cancelled,
                        cwd=directory,
                        env=git_env,
                        uid=uid,
                        gid=gid,
                    )
                    if result.returncode == 0:
                        result = _run_cancellable(
                            [executable, "-C", str(target), "checkout", "--force", "FETCH_HEAD"],
                            timeout=120,
                            cancelled=cancelled,
                            cwd=directory,
                            env=git_env,
                            uid=uid,
                            gid=gid,
                        )
                if result.returncode == 0 and bool(project.get("allow_submodules")) and (target / ".gitmodules").is_file():
                    result = _run_cancellable(
                        [executable, "-C", str(target), "submodule", "update", "--init", "--depth", "1"],
                        timeout=600,
                        cancelled=cancelled,
                        cwd=directory,
                        env=git_env,
                        uid=uid,
                        gid=gid,
                    )
            if result.returncode != 0:
                message = redact_text(result.stderr or result.stdout)[:2000]
                with self.store._lock, self.store.connect() as connection:
                    connection.execute("UPDATE projects SET last_sync_at=?,last_sync_status='failed',updated_at=?,updated_by=? WHERE id=?", (time.time(), time.time(), actor, project_id))
                    connection.execute("INSERT INTO project_sync_history(id,project_id,status,commit_hash,message,created_at,created_by) VALUES(?,?,?,?,?,?,?)", (self.store.root.name + os.urandom(8).hex(), project_id, "failed", "", message, time.time(), actor))
                self.store.audit(actor, "project", project_id, "sync", {"message": message}, result="failure")
                raise RuntimeError("Git project synchronization failed")
            repository_size = 0
            for path in target.rglob("*"):
                if path.is_symlink():
                    try:
                        path.resolve(strict=False).relative_to(target.resolve(strict=False))
                    except ValueError as error:
                        raise RuntimeError("Git project contains a symlink outside its managed directory") from error
                elif path.is_file():
                    repository_size += path.stat().st_size
                    if repository_size > 512 * 1024 * 1024:
                        raise RuntimeError("Git project exceeds the 512 MiB managed-project limit")
            if not bool(project.get("allow_submodules")) and (target / ".gitmodules").exists():
                raise RuntimeError("Git submodules are blocked for this project")
            commit = subprocess.run([executable, "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=False, shell=False).stdout.strip()[:64]
            with self.store._lock, self.store.connect() as connection:
                connection.execute("UPDATE projects SET last_commit=?,last_sync_at=?,last_sync_status='completed',updated_at=?,updated_by=? WHERE id=?", (commit, time.time(), time.time(), actor, project_id))
                connection.execute("INSERT INTO project_sync_history(id,project_id,status,commit_hash,message,created_at,created_by) VALUES(?,?,?,?,?,?,?)", (self.store.root.name + os.urandom(8).hex(), project_id, "completed", commit, "Git synchronization completed", time.time(), actor))
            self.store.audit(actor, "project", project_id, "sync", {"commit": commit})
            progress(100, "Git synchronization completed")
            return {"project_id": project_id, "commit": commit}
        if operation == "backup":
            progress(20, "Create private controller backup")
            result = create_backup(self.store, actor, str(payload.get("description") or ""), bool(payload.get("include_credentials")))
            progress(100, "Backup completed")
            return result
        if operation == "restore":
            progress(10, "Validate backup and checksum")
            backup_id = str(payload.get("backup_id") or "")
            checksum = str(payload.get("checksum") or "")
            if not checksum:
                checksum = next((str(item["checksum"]) for item in list_backups(self.store) if item["id"] == backup_id), "")
            result = restore_backup(self.store, backup_id, checksum, actor, bool(payload.get("include_credentials")))
            progress(100, "Restore completed")
            return result
        api_error(400, "ANSIBLE_OPERATION_NOT_SUPPORTED", "Unsupported Ansible controller operation")

    def execute_operation(self, action: PackageAction, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if action == PackageAction.apply:
            progress(30, "Validate controller configuration")
            result = self.save_config(dict(payload.get("config") or {}), actor)
            progress(100, "Controller configuration saved")
            return {"config": result}
        if action == PackageAction.restore:
            return self.manage("restore", payload, actor, log, progress, cancelled)
        return super().execute_operation(action, payload, actor, log, progress, cancelled)

    def awx_client(self) -> AwxClient:
        config = self.get_config().get("awx") or {}
        credential_id = str(config.get("credential_id") or "")
        if not config.get("url") or not credential_id:
            api_error(409, "AWX_NOT_CONFIGURED", "External AWX connection is not configured")
        credential = self.store.credential_secret(credential_id)
        if credential["type"] != CredentialType.awx_token.value:
            api_error(409, "AWX_CREDENTIAL_TYPE_INVALID", "External AWX requires an AWX token credential")
        token = credential["secret"]
        return AwxClient(str(config["url"]), token, verify_tls=bool(config.get("verify_tls", True)), ca_certificate=str(config.get("ca_certificate") or ""), timeout=int(config.get("timeout_seconds") or 15))
