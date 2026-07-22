from __future__ import annotations

import os
import hashlib
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ...config import get_config
from ...package_center.detached_updates import SESSION_ID_RE, read_update_state, update_session_directory, write_update_state
from ...package_center.distro import detect_distribution
from ...package_center.executor import apt_update_without_proxmox_enterprise, proxmox_enterprise_repository_failure, redact
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleStatus
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import CommandProvider


APT_INST_RE = re.compile(r"^Inst\s+(?P<name>[A-Za-z0-9][A-Za-z0-9+._:-]*)\s+(?:\[(?P<current>[^]]+)\]\s+)?\((?P<version>\S+)(?:\s+(?P<origin>[^)]+))?\)")
APT_SOURCE_RE = re.compile(r"^\s*(?P<disabled>#\s*)?(?P<kind>deb(?:-src)?)\s+(?:\[(?P<options>[^]]+)\]\s+)?(?P<uri>\S+)\s+(?P<suite>\S+)(?:\s+(?P<components>.*?))?\s*$")
REPOSITORY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REPOSITORY_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:/=@,-]{0,511}$")


class LinuxUpdatesProvider(CommandProvider):
    allowed_tools = {"apt-get", "dnf", "yum"}

    @property
    def update_state_root(self) -> Path:
        return Path(get_config().paths.data_dir)

    @property
    def apt_sources_root(self) -> Path:
        return Path("/etc/apt")

    @property
    def dnf_repositories_root(self) -> Path:
        return Path("/etc/yum.repos.d")

    @staticmethod
    def _repository_id(manager: str, path: Path, marker: str) -> str:
        return hashlib.sha256(f"{manager}\0{path}\0{marker}".encode()).hexdigest()[:24]

    @staticmethod
    def _repository_value(payload: dict[str, Any], key: str, *, required: bool = True, maximum: int = 512) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            if required:
                raise RuntimeError(f"Repository {key} is required")
            return ""
        value = value.strip()
        if (required and not value) or len(value) > maximum or "\n" in value or "\r" in value:
            raise RuntimeError(f"Invalid repository {key}")
        return value

    @classmethod
    def _repository_uri(cls, payload: dict[str, Any]) -> str:
        uri = cls._repository_value(payload, "uri")
        parsed = urlparse(uri)
        if parsed.scheme not in {"http", "https", "file"} or parsed.scheme != "file" and not parsed.netloc:
            raise RuntimeError("Repository URL must use http, https, or file")
        return uri

    @staticmethod
    def _safe_repository_path(path: Path, root: Path) -> None:
        if path.is_symlink():
            raise RuntimeError("Repository files cannot be symbolic links")
        resolved_root = root.resolve()
        resolved = path.resolve(strict=False)
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise RuntimeError("Repository file is outside the package manager configuration directory")

    @classmethod
    def _atomic_repository_write(cls, path: Path, content: str, root: Path) -> None:
        cls._safe_repository_path(path, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _apt_repositories(self) -> list[dict[str, Any]]:
        root = self.apt_sources_root
        paths = [root / "sources.list", *sorted((root / "sources.list.d").glob("*.list"))]
        repositories: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            self._safe_repository_path(path, root)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            occurrences: dict[str, int] = {}
            for index, line in enumerate(lines):
                match = APT_SOURCE_RE.match(line)
                if not match:
                    continue
                raw_key = line.strip()
                occurrence = occurrences.get(raw_key, 0)
                occurrences[raw_key] = occurrence + 1
                marker = f"{raw_key}\0{occurrence}"
                repositories.append({
                    "id": self._repository_id("apt", path, marker), "name": path.stem if path.name != "sources.list" else f"sources.list:{index + 1}",
                    "type": match.group("kind"), "uri": match.group("uri"), "suite": match.group("suite"),
                    "components": (match.group("components") or "").split(), "options": match.group("options") or "",
                    "enabled": not bool(match.group("disabled")), "file": str(path), "format": "apt-list", "managed": path.name.startswith("webnas-"),
                    "_path": path, "_line": index, "_marker": marker,
                })
        for path in sorted((root / "sources.list.d").glob("*.sources")):
            if not path.is_file() or path.is_symlink():
                continue
            self._safe_repository_path(path, root)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = 0
            while start < len(lines):
                while start < len(lines) and not lines[start].strip():
                    start += 1
                if start >= len(lines):
                    break
                end = start
                while end < len(lines) and lines[end].strip():
                    end += 1
                raw_lines = lines[start:end]
                fields: dict[str, str] = {}
                current_key = ""
                for line in raw_lines:
                    if line.lstrip().startswith("#"):
                        continue
                    if line[:1].isspace() and current_key:
                        fields[current_key] = f"{fields[current_key]} {line.strip()}".strip()
                        continue
                    match = re.match(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.*)$", line)
                    if match:
                        current_key = match.group(1).lower()
                        fields[current_key] = match.group(2).strip()
                if fields.get("uris") and fields.get("suites"):
                    marker = "\n".join(raw_lines)
                    signed_by = fields.get("signed-by", "")
                    repositories.append({
                        "id": self._repository_id("apt", path, marker), "name": f"{path.stem}:{start + 1}",
                        "type": (fields.get("types") or "deb").split()[0], "uri": fields["uris"], "suite": fields["suites"],
                        "components": fields.get("components", "").split(), "options": f"signed-by={signed_by}" if signed_by else "",
                        "enabled": fields.get("enabled", "yes").lower() not in {"no", "false", "0"}, "file": str(path), "format": "apt-deb822", "managed": path.name.startswith("webnas-"),
                        "_path": path, "_start": start, "_end": end, "_fields": fields,
                    })
                start = end + 1
        return repositories

    def _dnf_repositories(self) -> list[dict[str, Any]]:
        root = self.dnf_repositories_root
        repositories: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.repo")):
            if not path.is_file() or path.is_symlink():
                continue
            self._safe_repository_path(path, root)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            starts = [(index, match.group(1).strip()) for index, line in enumerate(lines) if (match := re.match(r"^\s*\[([^]]+)]\s*$", line))]
            for position, (start, section) in enumerate(starts):
                end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
                values: dict[str, str] = {}
                for line in lines[start + 1:end]:
                    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.*?)\s*$", line)
                    if match:
                        values[match.group(1).lower()] = match.group(2)
                source_key = next((key for key in ("baseurl", "metalink", "mirrorlist") if values.get(key)), "baseurl")
                repositories.append({
                    "id": self._repository_id("dnf", path, section), "name": values.get("name", section), "repository_id": section,
                    "type": source_key, "uri": values.get(source_key, ""), "suite": "", "components": [], "options": "",
                    "enabled": values.get("enabled", "1").lower() not in {"0", "false", "no"}, "gpgcheck": values.get("gpgcheck", "1").lower() not in {"0", "false", "no"},
                    "gpgkey": values.get("gpgkey", ""), "file": str(path), "format": "dnf-repo", "managed": path.name.startswith("webnas-"),
                    "_path": path, "_start": start, "_end": end, "_section": section, "_values": values,
                })
        return repositories

    def _repositories(self, manager: str | None = None) -> list[dict[str, Any]]:
        selected = manager or self._manager()
        return self._apt_repositories() if selected == "apt-get" else self._dnf_repositories() if selected in {"dnf", "yum"} else []

    def _repository(self, repository_id: Any, manager: str) -> dict[str, Any]:
        if not isinstance(repository_id, str) or not re.fullmatch(r"[0-9a-f]{24}", repository_id):
            raise RuntimeError("Invalid repository identifier")
        repository = next((item for item in self._repositories(manager) if item["id"] == repository_id), None)
        if not repository:
            raise RuntimeError("Repository no longer exists; reload the list")
        return repository

    def _apt_source_line(self, payload: dict[str, Any], *, enabled: bool, fallback: dict[str, Any] | None = None) -> str:
        fallback = fallback or {}
        kind = str(payload.get("type", fallback.get("type", "deb"))).strip()
        if kind not in {"deb", "deb-src"}:
            raise RuntimeError("APT repository type must be deb or deb-src")
        uri = self._repository_uri({"uri": payload.get("uri", fallback.get("uri"))})
        suite = self._repository_value({"suite": payload.get("suite", fallback.get("suite"))}, "suite")
        if not REPOSITORY_TOKEN_RE.fullmatch(suite):
            raise RuntimeError("Invalid APT distribution/suite")
        raw_components = payload.get("components", fallback.get("components", []))
        components = raw_components.split() if isinstance(raw_components, str) else raw_components
        if not isinstance(components, list) or any(not isinstance(value, str) or not REPOSITORY_TOKEN_RE.fullmatch(value) for value in components):
            raise RuntimeError("Invalid APT repository components")
        options = str(payload.get("options", fallback.get("options", ""))).strip()
        if options and (len(options) > 512 or "[" in options or "]" in options or "\n" in options):
            raise RuntimeError("Invalid APT repository options")
        body = f"{kind} {'[' + options + '] ' if options else ''}{uri} {suite}{' ' + ' '.join(components) if components else ''}"
        return body if enabled else f"# {body}"

    def _apt_deb822_lines(self, payload: dict[str, Any], *, enabled: bool, fallback: dict[str, Any]) -> list[str]:
        kind = str(payload.get("type", fallback.get("type", "deb"))).strip()
        if kind not in {"deb", "deb-src"}:
            raise RuntimeError("APT repository type must be deb or deb-src")
        raw_uris = str(payload.get("uri", fallback.get("uri", ""))).split()
        if not raw_uris:
            raise RuntimeError("Repository uri is required")
        for uri in raw_uris:
            self._repository_uri({"uri": uri})
        suites = str(payload.get("suite", fallback.get("suite", ""))).split()
        if not suites or any(not REPOSITORY_TOKEN_RE.fullmatch(value) for value in suites):
            raise RuntimeError("Invalid APT distribution/suite")
        raw_components = payload.get("components", fallback.get("components", []))
        components = raw_components.split() if isinstance(raw_components, str) else raw_components
        if not isinstance(components, list) or any(not isinstance(value, str) or not REPOSITORY_TOKEN_RE.fullmatch(value) for value in components):
            raise RuntimeError("Invalid APT repository components")
        raw_options = str(payload.get("options", fallback.get("options", ""))).strip()
        signed_by = raw_options.removeprefix("signed-by=").strip() if raw_options else ""
        if signed_by and (not signed_by.startswith(("/etc/apt/keyrings/", "/usr/share/keyrings/")) or any(value in signed_by for value in ("\n", "\r", ".."))):
            raise RuntimeError("APT Signed-By must reference /etc/apt/keyrings or /usr/share/keyrings")
        lines = [f"Types: {kind}", f"URIs: {' '.join(raw_uris)}", f"Suites: {' '.join(suites)}"]
        if components:
            lines.append(f"Components: {' '.join(components)}")
        if signed_by:
            lines.append(f"Signed-By: {signed_by}")
        lines.append(f"Enabled: {'yes' if enabled else 'no'}")
        return lines

    def _write_apt_repository(self, operation: str, payload: dict[str, Any], manager: str) -> dict[str, Any]:
        if operation == "repository_add":
            name = self._repository_value(payload, "name", maximum=64)
            if not REPOSITORY_NAME_RE.fullmatch(name):
                raise RuntimeError("Repository name may contain only letters, numbers, dots, dashes, and underscores")
            path = self.apt_sources_root / "sources.list.d" / f"webnas-{name.lower()}.list"
            if path.exists():
                raise RuntimeError("A repository with this name already exists")
            content = self._apt_source_line(payload, enabled=bool(payload.get("enabled", True))) + "\n"
            self._atomic_repository_write(path, content, self.apt_sources_root)
            return {"name": name, "file": str(path)}
        repository = self._repository(payload.get("repository_id"), manager)
        path = repository["_path"]
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if repository["format"] == "apt-deb822":
            start, end = int(repository["_start"]), int(repository["_end"])
            if operation == "repository_delete":
                replacement: list[str] = []
            elif operation in {"repository_enable", "repository_disable"}:
                replacement = self._apt_deb822_lines({}, enabled=operation == "repository_enable", fallback=repository)
            elif operation == "repository_update":
                replacement = self._apt_deb822_lines(payload, enabled=bool(payload.get("enabled", repository["enabled"])), fallback=repository)
            else:
                raise RuntimeError("Unsupported repository operation")
            lines[start:end] = replacement
            self._atomic_repository_write(path, "\n".join(lines) + ("\n" if lines else ""), self.apt_sources_root)
            return {"name": repository["name"], "file": str(path)}
        index = int(repository["_line"])
        if operation == "repository_delete":
            del lines[index]
        elif operation in {"repository_enable", "repository_disable"}:
            lines[index] = self._apt_source_line({}, enabled=operation == "repository_enable", fallback=repository)
        elif operation == "repository_update":
            lines[index] = self._apt_source_line(payload, enabled=bool(payload.get("enabled", repository["enabled"])), fallback=repository)
        else:
            raise RuntimeError("Unsupported repository operation")
        self._atomic_repository_write(path, "\n".join(lines) + ("\n" if lines else ""), self.apt_sources_root)
        return {"name": repository["name"], "file": str(path)}

    def _write_dnf_repository(self, operation: str, payload: dict[str, Any], manager: str) -> dict[str, Any]:
        if operation == "repository_add":
            repository_name = self._repository_value(payload, "name", maximum=64)
            if not REPOSITORY_NAME_RE.fullmatch(repository_name):
                raise RuntimeError("Invalid repository name")
            path = self.dnf_repositories_root / f"webnas-{repository_name.lower()}.repo"
            if path.exists():
                raise RuntimeError("A repository with this name already exists")
            uri = self._repository_uri(payload)
            content = f"[{repository_name}]\nname={repository_name}\nbaseurl={uri}\nenabled={'1' if payload.get('enabled', True) else '0'}\ngpgcheck={'1' if payload.get('gpgcheck', True) else '0'}\n"
            gpgkey = self._repository_value(payload, "gpgkey", required=False)
            if gpgkey:
                content += f"gpgkey={gpgkey}\n"
            self._atomic_repository_write(path, content, self.dnf_repositories_root)
            return {"name": repository_name, "file": str(path)}
        repository = self._repository(payload.get("repository_id"), manager)
        path = repository["_path"]
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start, end = int(repository["_start"]), int(repository["_end"])
        if operation == "repository_delete":
            replacement: list[str] = []
        else:
            values = dict(repository["_values"])
            if operation in {"repository_enable", "repository_disable"}:
                values["enabled"] = "1" if operation == "repository_enable" else "0"
            elif operation == "repository_update":
                values.update({"name": self._repository_value(payload, "name"), "baseurl": self._repository_uri(payload), "enabled": "1" if payload.get("enabled", repository["enabled"]) else "0", "gpgcheck": "1" if payload.get("gpgcheck", repository["gpgcheck"]) else "0"})
                values.pop("metalink", None)
                values.pop("mirrorlist", None)
                gpgkey = self._repository_value(payload, "gpgkey", required=False)
                if gpgkey:
                    values["gpgkey"] = gpgkey
                else:
                    values.pop("gpgkey", None)
            else:
                raise RuntimeError("Unsupported repository operation")
            replacement = [f"[{repository['_section']}]", *[f"{key}={value}" for key, value in values.items()]]
        lines[start:end] = replacement
        self._atomic_repository_write(path, "\n".join(lines) + ("\n" if lines else ""), self.dnf_repositories_root)
        return {"name": repository["name"], "file": str(path)}

    @staticmethod
    def _process_alive(pid: Any) -> bool:
        if not isinstance(pid, int) or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ValueError):
            return False
        return True

    @staticmethod
    def _screen_alive(screen: str, session_name: str) -> bool:
        result = subprocess.run(
            [screen, "-S", session_name, "-Q", "select", "."],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        return result.returncode == 0

    def _launch_screen(self, screen: str, session_name: str, directory: Path, session_id: str, command: list[str]) -> None:
        worker = Path(__file__).resolve().parents[1] / "linux_update_worker.py"
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        result = subprocess.run(
            # Lowercase -d starts screen detached and lets this launcher return
            # immediately. Uppercase -D keeps screen in the foreground and made
            # every package operation hit the ten-second launcher timeout.
            [screen, "-dmS", session_name, sys.executable, str(worker), "--state-dir", str(directory), "--session-id", session_id, "--", *command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
            env=clean_env,
        )
        if result.returncode != 0:
            error = redact(result.stderr.strip() or result.stdout.strip() or "GNU screen could not start the update worker")
            write_update_state(directory, {"session_id": session_id, "status": "failed", "finished_at": time.time(), "exit_code": result.returncode, "error": error})
            raise RuntimeError(error)

    @staticmethod
    def _forward_output(directory: Path, offset: int, log: LogCallback) -> int:
        try:
            with (directory / "output.log").open("rb") as handle:
                handle.seek(offset)
                output = handle.read()
                next_offset = handle.tell()
        except OSError:
            return offset
        for line in output.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                log("stdout", redact(line))
        return next_offset

    def _run_detached_update(self, command: list[str] | None, session_id: str, log: LogCallback, progress: ProgressCallback) -> dict[str, Any]:
        directory = update_session_directory(self.update_state_root, session_id)
        session_name = f"webnas-update-{session_id}"
        state = read_update_state(directory)
        screen_path = shutil.which("screen")
        if not screen_path and (not state or state["status"] not in {"completed", "failed"}):
            raise RuntimeError("GNU screen is required for durable system updates; install the 'screen' package or rerun the WebNAS installer")
        screen = screen_path or ""
        alive = self._screen_alive(screen, session_name) if state and screen else False
        worker_alive = self._process_alive((state or {}).get("pid"))

        if state and state["status"] == "running" and not alive and not worker_alive:
            refreshed = read_update_state(directory)
            if not refreshed or refreshed["status"] == "running":
                raise RuntimeError("Detached system update worker stopped before recording a result")
            state = refreshed
        if not state or (state["status"] == "launching" and not alive and not worker_alive):
            if command is None:
                raise RuntimeError("The detached update stopped before package execution and cannot be resumed safely")
            write_update_state(directory, {"session_id": session_id, "status": "launching", "started_at": time.time()})
            self._launch_screen(screen, session_name, directory, session_id, command)
            state = read_update_state(directory)

        progress(15, f"System update is running in screen session {session_name}")
        output_offset = 0
        started = time.monotonic()
        while True:
            output_offset = self._forward_output(directory, output_offset, log)
            state = read_update_state(directory)
            if state and state["status"] in {"completed", "failed"}:
                output_offset = self._forward_output(directory, output_offset, log)
                if state["status"] == "failed":
                    raise RuntimeError(redact(str(state.get("error") or "Detached system update failed")))
                progress(92, "Detached package operation completed")
                return {
                    "detached": True,
                    "screen_session": session_name,
                    "exit_code": int(state.get("exit_code", 0)),
                }
            if state and state["status"] == "running":
                alive = self._screen_alive(screen, session_name)
                if not alive and not self._process_alive(state.get("pid")):
                    time.sleep(0.2)
                    latest = read_update_state(directory)
                    if not latest or latest["status"] == "running":
                        raise RuntimeError("Detached system update worker stopped before recording a result")
            elapsed_progress = min(90, 15 + int((time.monotonic() - started) / 12))
            progress(elapsed_progress, f"System update continues in screen session {session_name}")
            time.sleep(1)

    def _manager(self) -> str | None:
        detected = detect_distribution().package_manager
        return detected if detected in self.allowed_tools and shutil.which(detected) else None

    def _packages(self) -> list[dict[str, Any]]:
        manager = self._manager()
        if manager == "apt-get":
            result = self._run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], timeout=90)
            output = self._result(result, "APT could not calculate available updates")
            packages: list[dict[str, Any]] = []
            for line in output.splitlines():
                match = APT_INST_RE.match(line)
                if not match:
                    continue
                origin = match.group("origin") or ""
                packages.append({"name": match.group("name"), "current_version": match.group("current") or "", "available_version": match.group("version"), "security": "security" in origin.lower(), "origin": origin})
            return packages
        if manager in {"dnf", "yum"}:
            result = self._run([manager, "-q", "check-update"], timeout=90)
            if result.returncode not in {0, 100}:
                self._result(result, f"{manager} could not calculate available updates")
            packages = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and "." in parts[0] and not parts[0].startswith(("Last", "Obsoleting")):
                    name, architecture = parts[0].rsplit(".", 1)
                    packages.append({"name": name, "architecture": architecture, "current_version": "", "available_version": parts[1], "security": False, "origin": parts[2]})
            security = self._run([manager, "-q", "updateinfo", "list", "security", "updates"], timeout=90)
            if security.returncode not in {0, 100}:
                self._result(security, f"{manager} could not calculate security updates")
            security_names = {part.rsplit(".", 1)[0] for line in security.stdout.splitlines() for part in line.split() if "." in part and not part.startswith("FEDORA-")}
            for package in packages:
                package["security"] = package["name"] in security_names
            return packages
        return []

    @staticmethod
    def _reboot_required() -> bool:
        if Path("/var/run/reboot-required").exists():
            return True
        executable = shutil.which("needs-restarting")
        if not executable:
            return False
        import subprocess

        return subprocess.run([executable, "-r"], capture_output=True, text=True, timeout=20, check=False, shell=False).returncode == 1

    def get_status(self) -> ModuleStatus:
        manager = self._manager()
        package_error = ""
        try:
            packages = self._packages() if manager else []
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            packages = []
            package_error = redact(str(error))[:500]
        security = sum(1 for item in packages if item["security"])
        reboot = self._reboot_required()
        screen_available = bool(shutil.which("screen"))
        health_message = f"{len(packages)} updates, {security} security updates" if manager else "A supported package manager is unavailable"
        if package_error:
            health_message = f"Could not read available updates: {package_error}"
        elif manager and not screen_available:
            health_message = "GNU screen is unavailable; install it before starting a durable update"
        return ModuleStatus(
            installed=bool(manager), package_version=None, update_available=bool(packages), service_state="not_applicable",
            configuration_valid=False if package_error else True if manager else None,
            health=ModuleHealth.failed if package_error else ModuleHealth.degraded if security or reboot or (manager and not screen_available) else ModuleHealth.healthy if manager else ModuleHealth.not_installed,
            health_message=health_message,
            metrics={"updates": len(packages), "security_updates": security, "reboot_required": reboot, "package_manager": manager, "screen_available": screen_available, "package_query_error": package_error},
        )

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        if resource == "repositories":
            items = [{key: value for key, value in item.items() if not key.startswith("_")} for item in self._repositories()]
            needle = search.lower().strip()
            if needle:
                items = [item for item in items if needle in " ".join(str(item.get(key, "")) for key in ("name", "uri", "suite", "file")).lower()]
            return {"resource": resource, "items": items[:limit], "total": len(items)}
        if resource in {"packages", "security"}:
            items = self._packages()
            if resource == "security":
                items = [item for item in items if item["security"]]
            needle = search.lower().strip()
            if needle:
                items = [item for item in items if needle in str(item.get("name", "")).lower()]
            return {"resource": resource, "items": items[:limit], "total": len(items), "reboot_required": self._reboot_required()}
        if resource == "history":
            manager = self._manager()
            lines: list[str] = []
            if manager == "apt-get":
                path = Path("/var/log/apt/history.log")
                if path.is_file():
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
            elif manager in {"dnf", "yum"}:
                lines = self._run([manager, "history", "list", "--reverse"], timeout=30).stdout.splitlines()[-limit:]
            return {"resource": resource, "items": [{"entry": redact(line)} for line in lines], "total": len(lines), "reboot_required": self._reboot_required()}
        if resource == "reboot":
            return {"resource": resource, "items": [{"required": self._reboot_required()}], "total": 1}
        return super().list_resources(resource, limit=limit, search=search)

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        manager = self._manager()
        if not manager:
            raise RuntimeError("A supported package manager is unavailable")
        if operation in {"repository_add", "repository_update", "repository_enable", "repository_disable", "repository_delete"}:
            progress(20, "Validating repository configuration")
            if cancelled():
                raise InterruptedError("Repository operation cancelled before execution")
            changed = self._write_apt_repository(operation, payload, manager) if manager == "apt-get" else self._write_dnf_repository(operation, payload, manager)
            log("stdout", f"Repository operation {operation} completed for {changed['name']}")
            progress(95, "Repository configuration saved")
            return {"operation": operation, "repository": changed}
        requested_session = payload.get("screen_session")
        if requested_session is not None and (not isinstance(requested_session, str) or not SESSION_ID_RE.fullmatch(requested_session)):
            raise RuntimeError("Invalid detached update session identifier")
        if operation in {"upgrade_all", "upgrade_security"} and requested_session:
            existing = read_update_state(update_session_directory(self.update_state_root, requested_session))
            if existing:
                progress(10, "Reconnecting to detached system update")
                resumed = self._run_detached_update(None, requested_session, log, progress)
                progress(95, "Checking restart requirement")
                return {"operation": operation, **resumed, "reboot_required": self._reboot_required(), "remaining_updates": len(self._packages())}
        if operation == "refresh":
            command = ["apt-get", "update"] if manager == "apt-get" else [manager, "makecache"]
        elif operation == "upgrade_all":
            command = ["apt-get", "upgrade", "-y"] if manager == "apt-get" else [manager, "upgrade", "-y"]
        elif operation == "upgrade_security":
            if manager == "apt-get":
                names = [self._checked_identifier(item["name"], "package name") for item in self._packages() if item["security"]]
                if not names:
                    return {"updated": 0, "reboot_required": self._reboot_required()}
                command = ["apt-get", "install", "--only-upgrade", "-y", *names]
            else:
                command = [manager, "upgrade", "--security", "-y"]
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        progress(10, "Preparing package operation")
        if cancelled():
            raise InterruptedError("System update cancelled before execution")
        detached: dict[str, Any] = {}
        if operation in {"upgrade_all", "upgrade_security"}:
            detached = self._run_detached_update(command, requested_session or secrets.token_hex(12), log, progress)
        else:
            result = self._run(command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})
            if manager == "apt-get" and operation == "refresh" and result.returncode != 0 and proxmox_enterprise_repository_failure(result.stdout + "\n" + result.stderr):
                with apt_update_without_proxmox_enterprise() as (retry_command, removed):
                    if removed:
                        log("warning", "Proxmox Enterprise repository is unavailable without a subscription; retrying APT metadata refresh with that repository temporarily omitted")
                        result = self._run(retry_command, timeout=3600, env={"DEBIAN_FRONTEND": "noninteractive"})
            for line in (result.stdout + "\n" + result.stderr).splitlines()[-500:]:
                log("stdout" if result.returncode == 0 else "stderr", line)
            self._result(result, "System update failed")
        progress(95, "Checking restart requirement")
        return {"operation": operation, **detached, "reboot_required": self._reboot_required(), "remaining_updates": len(self._packages())}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        return [
            ModuleDiagnostic(status="ok" if status.installed else "critical", title="Package manager", description=str(status.metrics.get("package_manager") or "Unavailable"), severity="ok" if status.installed else "critical"),
            ModuleDiagnostic(status="ok" if status.metrics.get("screen_available") else "critical", title="Detached update worker", description="GNU screen available" if status.metrics.get("screen_available") else "Install the screen package", severity="ok" if status.metrics.get("screen_available") else "critical", recommended_action="Install GNU screen or rerun the WebNAS installer" if not status.metrics.get("screen_available") else ""),
            ModuleDiagnostic(status="warning" if status.metrics.get("security_updates") else "ok", title="Security updates", description=str(status.metrics.get("security_updates", 0)), severity="warning" if status.metrics.get("security_updates") else "ok", recommended_action="Install security updates" if status.metrics.get("security_updates") else ""),
            ModuleDiagnostic(status="warning" if status.metrics.get("reboot_required") else "ok", title="Restart required", description="Yes" if status.metrics.get("reboot_required") else "No", severity="warning" if status.metrics.get("reboot_required") else "ok"),
        ]
