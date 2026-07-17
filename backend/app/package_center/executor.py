from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from typing import Iterator

from .manifests import module_script
from .models import ModuleManifest, PackageAction, PackagePlan

LogCallback = Callable[[str, str], None]
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]

SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
    "HOME": "/root",
}
SECRET_RE = re.compile(r"(?i)(password|passwd|token|secret|authorization)(\s*[:=]\s*)(\S+)")
URL_SECRET_RE = re.compile(r"(?i)(https?://[^:/\s]+:)[^@\s]+@")
BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
SQL_SECRET_RE = re.compile(r"(?i)((?:identified\s+by|password)\s+')[^']*'")
PROXMOX_ENTERPRISE_HOST = "enterprise.proxmox.com"
APT_SOURCES_ROOT = Path("/etc/apt")
DPKG_OVERWRITE_CONFLICT_RE = re.compile(
    r"trying to overwrite\s+['\"](?P<path>[^'\"]+)['\"],\s+which is also in package\s+(?P<owner>[A-Za-z0-9][A-Za-z0-9+.:~-]*)",
    re.IGNORECASE,
)
SAFE_CIFS_USRMERGE_PATHS = frozenset({
    "/sbin/mount.cifs",
    "/usr/sbin/mount.cifs",
    "/sbin/umount.cifs",
    "/usr/sbin/umount.cifs",
})


class CommandExecutionError(RuntimeError):
    def __init__(self, executable: str, exit_code: int, output: str) -> None:
        super().__init__(f"{executable} failed with exit code {exit_code}")
        self.executable = executable
        self.exit_code = exit_code
        self.output = output


def redact(line: str) -> str:
    cleaned = line.replace("\x00", "")
    cleaned = URL_SECRET_RE.sub(r"\1[REDACTED]@", cleaned)
    cleaned = BEARER_RE.sub(r"\1[REDACTED]", cleaned)
    cleaned = SQL_SECRET_RE.sub(r"\1[REDACTED]'", cleaned)
    return SECRET_RE.sub(r"\1\2[REDACTED]", cleaned)[-4000:]


def proxmox_enterprise_repository_failure(output: str) -> bool:
    normalized = output.lower()
    return PROXMOX_ENTERPRISE_HOST in normalized and any(
        marker in normalized
        for marker in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "subscription",
            "authentication required",
            "does not have a release file",
            "no longer has a release file",
            "is not signed",
        )
    )


def _filter_apt_source(path: Path, content: str) -> tuple[str, int]:
    if path.suffix == ".sources":
        stanzas = re.split(r"\n\s*\n", content.strip()) if content.strip() else []
        kept = [stanza for stanza in stanzas if PROXMOX_ENTERPRISE_HOST not in stanza.lower()]
        removed = len(stanzas) - len(kept)
        return ("\n\n".join(kept) + ("\n" if kept else ""), removed)
    lines = content.splitlines(keepends=True)
    kept_lines = [line for line in lines if PROXMOX_ENTERPRISE_HOST not in line.lower()]
    return "".join(kept_lines), len(lines) - len(kept_lines)


@contextmanager
def apt_command_without_proxmox_enterprise(command: list[str], source_root: Path | None = None) -> Iterator[tuple[list[str], int]]:
    """Run a closed APT command against an ephemeral source view without Enterprise."""

    if not command or command[0] != "apt-get":
        raise ValueError("Only apt-get commands can use the Proxmox repository fallback")

    root = source_root or APT_SOURCES_ROOT
    with tempfile.TemporaryDirectory(prefix="webnas-apt-") as temporary:
        temporary_root = Path(temporary)
        source_list = temporary_root / "sources.list"
        source_parts = temporary_root / "sources.list.d"
        source_parts.mkdir(mode=0o700)
        removed = 0

        main_source = root / "sources.list"
        main_content = main_source.read_text(encoding="utf-8", errors="replace") if main_source.is_file() else ""
        filtered_main, count = _filter_apt_source(main_source, main_content)
        removed += count
        source_list.write_text(filtered_main, encoding="utf-8")

        parts = root / "sources.list.d"
        candidates = sorted([*parts.glob("*.list"), *parts.glob("*.sources")]) if parts.is_dir() else []
        for candidate in candidates:
            filtered, count = _filter_apt_source(candidate, candidate.read_text(encoding="utf-8", errors="replace"))
            removed += count
            if filtered.strip():
                (source_parts / candidate.name).write_text(filtered, encoding="utf-8")

        retry_command = [
            "apt-get",
            "-o", f"Dir::Etc::sourcelist={source_list}",
            "-o", f"Dir::Etc::sourceparts={source_parts}",
            *command[1:],
        ]
        yield retry_command, removed


@contextmanager
def apt_update_without_proxmox_enterprise(source_root: Path | None = None) -> Iterator[tuple[list[str], int]]:
    """Backward-compatible temporary source view for an APT metadata refresh."""

    with apt_command_without_proxmox_enterprise(["apt-get", "update"], source_root) as result:
        yield result


def _command_steps(plan: PackagePlan, manifest: ModuleManifest) -> list[tuple[str, list[str], int]]:
    manager = plan.distribution.package_manager
    packages = plan.packages
    steps: list[tuple[str, list[str], int]] = []
    required_services = [service.name for service in manifest.services if service.required]
    if plan.action in {PackageAction.install, PackageAction.update}:
        if manager == "apt-get":
            steps.append(("Refresh package metadata", ["apt-get", "update"], 900))
            steps.append(("Install packages", ["apt-get", "install", "-y", "--no-install-recommends", *packages], 1800))
        elif manager in {"dnf", "yum"}:
            steps.append(("Install packages", [manager, "install", "-y", *packages], 1800))
        steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
        for service in required_services:
            steps.append((f"Enable {service}", ["systemctl", "enable", service], 120))
            steps.append((f"Start {service}", ["systemctl", "start", service], 180))
    elif plan.action == PackageAction.reinstall:
        if manager == "apt-get":
            steps.append(("Refresh package metadata", ["apt-get", "update"], 900))
            steps.append(("Reinstall packages", ["apt-get", "install", "-y", "--reinstall", "--no-install-recommends", *packages], 1800))
        elif manager in {"dnf", "yum"}:
            steps.append(("Reinstall packages", [manager, "reinstall", "-y", *packages], 1800))
        steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
        for service in required_services:
            steps.append((f"Enable {service}", ["systemctl", "enable", service], 120))
            steps.append((f"Start {service}", ["systemctl", "start", service], 180))
    elif plan.action == PackageAction.uninstall:
        for service in reversed(required_services):
            steps.append((f"Stop {service}", ["systemctl", "stop", service], 180))
            steps.append((f"Disable {service}", ["systemctl", "disable", service], 120))
        if manager == "apt-get":
            steps.append(("Remove packages", ["apt-get", "remove", "-y", *packages], 1800))
        elif manager in {"dnf", "yum"}:
            steps.append(("Remove packages", [manager, "remove", "-y", *packages], 1800))
        steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
    elif plan.action in {PackageAction.start, PackageAction.stop, PackageAction.restart}:
        for service in required_services:
            steps.append((f"{plan.action.value.title()} {service}", ["systemctl", plan.action.value, service], 180))
    return steps


def command_preview(plan: PackagePlan, manifest: ModuleManifest) -> list[list[str]]:
    return [args for _, args, _ in _command_steps(plan, manifest)]


def _run(args: list[str], timeout: int, log: LogCallback) -> None:
    if not args or shutil.which(args[0]) is None:
        raise RuntimeError(f"Required executable is unavailable: {args[0] if args else 'unknown'}")
    log("command", " ".join(args))
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=False,
        env=SAFE_ENV,
        start_new_session=True,
    )

    output: list[str] = []

    def drain(stream, name: str) -> None:
        if stream is None:
            return
        for line in stream:
            cleaned = redact(line.rstrip())
            output.append(cleaned)
            log(name, cleaned)

    readers = [
        threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        raise RuntimeError(f"{Path(args[0]).name} timed out after {timeout} seconds") from error
    finally:
        for reader in readers:
            reader.join(timeout=2)
    if code != 0:
        raise CommandExecutionError(Path(args[0]).name, code, "\n".join(output))


def _is_safe_cifs_usrmerge_conflict(args: list[str], output: str) -> bool:
    """Recognize only the cifs-utils self-conflict caused by /usr path aliases."""

    if "cifs-utils" not in args:
        return False
    conflicts = list(DPKG_OVERWRITE_CONFLICT_RE.finditer(output))
    if not conflicts or output.lower().count("trying to overwrite") != len(conflicts):
        return False
    return all(
        match.group("path") in SAFE_CIFS_USRMERGE_PATHS
        and match.group("owner").split(":", 1)[0] == "cifs-utils"
        for match in conflicts
    )


def _temporary_apt_source_options(args: list[str]) -> list[str]:
    """Keep only the internally generated temporary APT source options."""

    options: list[str] = []
    index = 1
    while index + 1 < len(args) and args[index] == "-o":
        value = args[index + 1]
        if value.startswith(("Dir::Etc::sourcelist=", "Dir::Etc::sourceparts=")):
            options.extend(["-o", value])
        index += 2
    return options


def _run_apt_with_cifs_recovery(args: list[str], timeout: int, log: LogCallback) -> None:
    try:
        _run(args, timeout, log)
        return
    except CommandExecutionError as error:
        if not _is_safe_cifs_usrmerge_conflict(args, error.output):
            raise

    source_options = _temporary_apt_source_options(args)
    log("warning", "Detected a cifs-utils merged-/usr self-conflict; repairing only cifs-utils before retrying the requested operation")
    repair = [
        "apt-get",
        *source_options,
        "-o", "Dpkg::Options::=--force-overwrite",
        "install", "-y", "--reinstall", "--no-install-recommends", "cifs-utils",
    ]
    _run(repair, timeout, log)
    log("stdout", "cifs-utils repair completed; retrying the original package operation")
    _run(args, timeout, log)


def _run_apt_command(args: list[str], timeout: int, log: LogCallback) -> None:
    if not args or args[0] != "apt-get":
        raise ValueError("APT fallback received a non-APT command")
    try:
        _run_apt_with_cifs_recovery(args, timeout, log)
    except CommandExecutionError as error:
        if not proxmox_enterprise_repository_failure(error.output):
            raise
        with apt_command_without_proxmox_enterprise(args) as (command, removed):
            if removed == 0:
                raise
            log("warning", "Proxmox Enterprise repository requires an active subscription; retrying the APT operation with that repository temporarily omitted")
            _run_apt_with_cifs_recovery(command, timeout, log)


def _run_apt_update(timeout: int, log: LogCallback) -> None:
    """Compatibility wrapper retained for callers and extensions."""

    _run_apt_command(["apt-get", "update"], timeout, log)


def _run_hook(manifest: ModuleManifest, action: str, log: LogCallback) -> None:
    script = module_script(manifest.id, action)
    if not script:
        return
    args = [sys.executable, str(script)] if script.suffix == ".py" else ["/bin/bash", str(script)]
    _run(args, 300, log)


def _remove_data(manifest: ModuleManifest, log: LogCallback) -> None:
    for raw in manifest.data_paths:
        path = Path(raw).resolve(strict=False)
        if path == Path("/") or len(path.parts) < 3:
            raise RuntimeError(f"Refusing unsafe data path: {path}")
        if not path.exists():
            continue
        log("stdout", f"Removing module data: {path}")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def execute(plan: PackagePlan, manifest: ModuleManifest, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> None:
    if manifest.requires_root and hasattr(os, "geteuid") and os.geteuid() != 0:
        raise PermissionError("Package operations require the WebNAS service to run as root")
    steps = _command_steps(plan, manifest)
    total = max(1, len(steps) + 1)
    hook_complete = False
    for index, (label, args, timeout) in enumerate(steps):
        if cancelled():
            raise InterruptedError("Package operation cancelled before the next safe step")
        progress(max(1, int(index / total * 90)), label)
        if args and args[0] == "apt-get":
            _run_apt_command(args, timeout, log)
        else:
            _run(args, timeout, log)
        if label in {"Install packages", "Reinstall packages", "Remove packages"} and plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update, PackageAction.uninstall}:
            hook_action = "install" if plan.action == PackageAction.reinstall else plan.action.value
            progress(max(1, int((index + 0.5) / total * 90)), f"Run trusted {hook_action} hook")
            _run_hook(manifest, hook_action, log)
            hook_complete = True
    if plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update, PackageAction.uninstall} and not hook_complete:
        hook_action = "install" if plan.action == PackageAction.reinstall else plan.action.value
        progress(92, f"Run trusted {hook_action} hook")
        _run_hook(manifest, hook_action, log)
    if plan.action == PackageAction.uninstall and plan.remove_data:
        progress(96, "Remove module data")
        _remove_data(manifest, log)
    if plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update} and manifest.healthcheck:
        progress(97, "Run health check")
        _run_hook(manifest, "health", log)
    if plan.action == PackageAction.uninstall:
        progress(98, "Verify packages were removed")
        manager = plan.distribution.package_manager
        if manager == "apt-get" and shutil.which("dpkg-query"):
            for package in plan.packages:
                result = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], capture_output=True, text=True, timeout=20, check=False, shell=False)
                if result.returncode == 0 and result.stdout.strip().startswith("ii"):
                    raise RuntimeError(f"Package is still installed after removal: {package}")
        elif manager in {"dnf", "yum"} and shutil.which("rpm"):
            for package in plan.packages:
                result = subprocess.run(["rpm", "-q", package], capture_output=True, text=True, timeout=20, check=False, shell=False)
                if result.returncode == 0:
                    raise RuntimeError(f"Package is still installed after removal: {package}")
    progress(100, "Completed")
