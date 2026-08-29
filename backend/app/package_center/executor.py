from __future__ import annotations

import os
import re
import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from typing import Iterator

from .manifests import module_script
from .models import InstallationType, ModuleManifest, PackageAction, PackagePlan
from .distro import installation_for
from .package_managers import resolve_package_manager_executable
from ..config import get_config
from ..privileged_broker.runtime import broker_command, broker_required, module_hook

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
SYSTEM_MUTATION_COMMANDS = frozenset({
    "apt-get", "apt", "dpkg", "dnf", "yum", "zypper", "pacman", "apk", "rpm", "systemctl",
})
SHARED_RUNTIME_ROOT = Path("/run/webnas-package-center")
# Packages required by WebNAS itself must never be removed with an optional module.
PROTECTED_RUNTIME_PACKAGES = frozenset({"cifs-utils"})
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
DPKG_CIFS_SUID_PERMISSION_RE = re.compile(
    r"error setting permissions of\s+['\"]\.?/(?:usr/)?sbin/mount\.cifs['\"]:\s*Operation not permitted",
    re.IGNORECASE,
)
DPKG_BAD_STATE_REMOVAL_RE = re.compile(
    r"dpkg:\s+error processing package\s+(?P<package>[A-Za-z0-9][A-Za-z0-9+.:~-]*)\s+"
    r"\(--(?:remove|purge)\):\s*package is in a very bad inconsistent state;\s*"
    r"you should\s*reinstall it before attempting a removal",
    re.IGNORECASE | re.DOTALL,
)


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
    with _shared_temporary_directory("webnas-apt-") as temporary:
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



def _package_base_name(package: str) -> str:
    """Normalize architecture-qualified package names for protection checks."""

    return package.strip().lower().split(":", 1)[0]


def _partition_uninstall_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    """Split a module package list into removable and WebNAS-protected packages."""

    removable: list[str] = []
    protected: list[str] = []
    for package in packages:
        destination = protected if _package_base_name(package) in PROTECTED_RUNTIME_PACKAGES else removable
        destination.append(package)
    return removable, protected


def _command_steps(plan: PackagePlan, manifest: ModuleManifest) -> list[tuple[str, list[str], int]]:
    manager = plan.distribution.package_manager
    executable = resolve_package_manager_executable(manager, shutil.which)
    packages = plan.packages
    if plan.action == PackageAction.uninstall:
        packages, _protected = _partition_uninstall_packages(packages)
    steps: list[tuple[str, list[str], int]] = []
    required_services = [service.name for service in manifest.services if service.required]
    uses_system_packages = plan.installation_type in {None, InstallationType.system_package}
    removes_named_packages = plan.installation_type in {None, InstallationType.system_package, InstallationType.download_package}
    if plan.action in {PackageAction.install, PackageAction.update}:
        if uses_system_packages and manager == "apt-get":
            steps.append(("Refresh package metadata", ["apt-get", "update"], 900))
            steps.append(("Install packages", ["apt-get", "install", "-y", "--no-install-recommends", *packages], 1800))
        elif uses_system_packages and manager in {"dnf", "yum"}:
            steps.append(("Install packages", [executable or manager, "install", "-y", *packages], 1800))
        elif uses_system_packages and manager == "zypper":
            steps.append(("Install packages", [executable or manager, "--non-interactive", "install", *packages], 1800))
        elif uses_system_packages and manager == "pacman":
            steps.append(("Install packages", [executable or manager, "-S", "--noconfirm", "--needed", *packages], 1800))
        elif uses_system_packages and manager == "apk":
            steps.append(("Install packages", [executable or manager, "add", *packages], 1800))
        if required_services:
            steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
        for service in required_services:
            steps.append((f"Enable {service}", ["systemctl", "enable", service], 120))
            steps.append((f"Start {service}", ["systemctl", "start", service], 180))
    elif plan.action == PackageAction.reinstall:
        if uses_system_packages and manager == "apt-get":
            steps.append(("Refresh package metadata", ["apt-get", "update"], 900))
            steps.append(("Reinstall packages", ["apt-get", "install", "-y", "--reinstall", "--no-install-recommends", *packages], 1800))
        elif uses_system_packages and manager in {"dnf", "yum"}:
            steps.append(("Reinstall packages", [executable or manager, "reinstall", "-y", *packages], 1800))
        elif uses_system_packages and manager == "zypper":
            steps.append(("Reinstall packages", [executable or manager, "--non-interactive", "install", "--force", *packages], 1800))
        elif uses_system_packages and manager == "pacman":
            steps.append(("Reinstall packages", [executable or manager, "-S", "--noconfirm", *packages], 1800))
        elif uses_system_packages and manager == "apk":
            steps.append(("Reinstall packages", [executable or manager, "fix", *packages], 1800))
        if required_services:
            steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
        for service in required_services:
            steps.append((f"Enable {service}", ["systemctl", "enable", service], 120))
            steps.append((f"Start {service}", ["systemctl", "start", service], 180))
    elif plan.action == PackageAction.uninstall:
        for service in reversed(required_services):
            steps.append((f"Stop {service}", ["systemctl", "stop", service], 180))
            steps.append((f"Disable {service}", ["systemctl", "disable", service], 120))
        if removes_named_packages and packages and manager == "apt-get":
            steps.append(("Remove packages", ["apt-get", "remove", "-y", *packages], 1800))
        elif removes_named_packages and packages and manager in {"dnf", "yum"}:
            steps.append(("Remove packages", [executable or manager, "remove", "-y", *packages], 1800))
        elif removes_named_packages and packages and manager == "zypper":
            steps.append(("Remove packages", [executable or manager, "--non-interactive", "remove", *packages], 1800))
        elif removes_named_packages and packages and manager == "pacman":
            steps.append(("Remove packages", [executable or manager, "-R", "--noconfirm", *packages], 1800))
        elif removes_named_packages and packages and manager == "apk":
            steps.append(("Remove packages", [executable or manager, "del", *packages], 1800))
        if required_services:
            steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
    elif plan.action in {PackageAction.start, PackageAction.stop, PackageAction.restart}:
        for service in required_services:
            steps.append((f"{plan.action.value.title()} {service}", ["systemctl", plan.action.value, service], 180))
    return steps


def command_preview(plan: PackagePlan, manifest: ModuleManifest) -> list[list[str]]:
    if plan.installation_type == InstallationType.command and plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update, PackageAction.uninstall}:
        hook_action = "install" if plan.action == PackageAction.reinstall else plan.action.value
        script = module_script(manifest.id, hook_action)
        if script:
            return [[sys.executable if script.suffix == ".py" else "/bin/bash", str(script)]]
    if plan.installation_type == InstallationType.download_package and plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update}:
        installation = installation_for(manifest, plan.distribution)
        if installation and installation.package_format:
            return [["dpkg", "--install", "<verified-download.deb>"] if installation.package_format == "deb" else ["rpm", "-Uvh", "<verified-download.rpm>"]]
    return [args for _, args, _ in _command_steps(plan, manifest)]


def _shared_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    """Create package files in a directory visible to the privileged broker."""

    if broker_required():
        runtime = Path(get_config().paths.data_dir) / "package-center-runtime"
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(runtime, 0o700)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=runtime)
    try:
        SHARED_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(SHARED_RUNTIME_ROOT, 0o700)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=SHARED_RUNTIME_ROOT)
    except OSError:
        return tempfile.TemporaryDirectory(prefix=prefix)


def _transient_admin_command(args: list[str], timeout: int) -> list[str]:
    """Escape the backend unit's read-only mount namespace for trusted system mutations."""

    if not args or Path(args[0]).name not in SYSTEM_MUTATION_COMMANDS:
        return args
    systemd_run = shutil.which("systemd-run")
    executable = shutil.which(args[0])
    if not systemd_run or not executable or not Path("/run/systemd/system").exists():
        return args
    return [
        systemd_run,
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--service-type=exec",
        f"--property=RuntimeMaxSec={max(1, timeout)}s",
        "--property=ProtectSystem=false",
        "--property=ProtectHome=false",
        "--property=PrivateTmp=false",
        "--property=NoNewPrivileges=false",
        "--property=RestrictSUIDSGID=false",
        f"--setenv=PATH={SAFE_ENV['PATH']}",
        f"--setenv=LANG={SAFE_ENV['LANG']}",
        f"--setenv=LC_ALL={SAFE_ENV['LC_ALL']}",
        f"--setenv=DEBIAN_FRONTEND={SAFE_ENV['DEBIAN_FRONTEND']}",
        "--",
        executable,
        *args[1:],
    ]


def _run(args: list[str], timeout: int, log: LogCallback) -> None:
    if not args:
        raise RuntimeError("Required executable is unavailable: unknown")
    log("command", " ".join(args))
    if broker_required():
        broker_result = broker_command(args, timeout=timeout, actor="package-center")
        if broker_result is not None:
            for line in broker_result.stdout.splitlines():
                log("stdout", redact(line))
            for line in broker_result.stderr.splitlines():
                log("stderr", redact(line))
            if broker_result.returncode != 0:
                raise CommandExecutionError(Path(args[0]).name, broker_result.returncode, broker_result.stderr or broker_result.stdout)
            return
    if shutil.which(args[0]) is None:
        raise RuntimeError(f"Required executable is unavailable: {args[0]}")
    execution_args = _transient_admin_command(args, timeout)
    if execution_args is not args:
        log("stdout", "Executing trusted system mutation in a transient administrative systemd unit")
    process = subprocess.Popen(
        execution_args,
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


def _is_cifs_suid_sandbox_failure(args: list[str], output: str) -> bool:
    """Recognize dpkg being blocked from restoring mount.cifs' SUID mode."""

    return "cifs-utils" in args and bool(DPKG_CIFS_SUID_PERMISSION_RE.search(output))


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


def _apt_subcommand_index(args: list[str]) -> int | None:
    """Return the APT operation index after internally generated -o options."""

    index = 1
    while index + 1 < len(args) and args[index] == "-o":
        index += 2
    return index if index < len(args) else None


def _bad_state_removal_packages(args: list[str], output: str) -> list[str]:
    """Return explicitly requested packages that dpkg requires to be reinstalled first."""

    command_index = _apt_subcommand_index(args)
    if command_index is None or args[command_index] not in {"remove", "purge"}:
        return []

    requested = {
        item.split("=", 1)[0]
        for item in args[command_index + 1 :]
        if item and not item.startswith("-")
    }
    result: list[str] = []
    for match in DPKG_BAD_STATE_REMOVAL_RE.finditer(output):
        package = match.group("package")
        base_package = package.split(":", 1)[0]
        if package not in requested and base_package not in requested:
            continue
        selected = package if package in requested else base_package
        if selected not in result:
            result.append(selected)
    return result


def _run_apt_with_cifs_recovery(args: list[str], timeout: int, log: LogCallback) -> None:
    try:
        _run(args, timeout, log)
        return
    except CommandExecutionError as error:
        bad_state_packages = _bad_state_removal_packages(args, error.output)
        if bad_state_packages:
            source_options = _temporary_apt_source_options(args)
            package_list = ", ".join(bad_state_packages)
            log(
                "warning",
                (
                    f"dpkg reports an inconsistent package state for {package_list}; "
                    "reinstalling the affected package before retrying removal"
                ),
            )
            repair = [
                "apt-get",
                *source_options,
                "install", "-y", "--reinstall", "--no-install-recommends",
                *bad_state_packages,
            ]
            _run_apt_command(repair, timeout, log)
            log("stdout", f"Package repair completed for {package_list}; retrying the original removal")
            _run(args, timeout, log)
            return

        if _is_cifs_suid_sandbox_failure(args, error.output):
            message = (
                "The installed WebNAS systemd sandbox blocks the SUID mode required by cifs-utils/mount.cifs. "
                "Update or reinstall WebNAS to regenerate webnas.service, restart WebNAS, and retry this operation."
            )
            log("stderr", message)
            raise RuntimeError(message) from error
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


def _run_systemctl_command(args: list[str], timeout: int, log: LogCallback) -> None:
    if not args or args[0] != "systemctl":
        raise ValueError("systemctl fallback received a non-systemctl command")
    try:
        _run(args, timeout, log)
    except CommandExecutionError as error:
        if "read-only file system" not in error.output.lower():
            raise

        action = args[1] if len(args) > 1 else ""
        service = args[-1] if len(args) > 2 else "service"
        if action == "disable":
            log(
                "warning",
                (
                    f"Persistent disable of {service} was skipped because service metadata is on a read-only filesystem. "
                    "The service was already stopped; package removal will continue."
                ),
            )
            return

        log("warning", "systemctl encountered a read-only filesystem; temporarily remounting root as read-write")
        try:
            _run(["mount", "-o", "remount,rw", "/"], 30, log)
        except Exception as mount_error:
            raise RuntimeError(f"Failed to remount root filesystem as read-write: {mount_error}") from error
        try:
            _run(args, timeout, log)
        finally:
            log("stdout", "Restoring root filesystem to read-only")
            try:
                _run(["mount", "-o", "remount,ro", "/"], 30, log)
            except Exception as unmount_error:
                log("warning", f"Failed to restore root filesystem to read-only: {unmount_error}")


def _run_hook(manifest: ModuleManifest, action: str, log: LogCallback) -> None:
    script = module_script(manifest.id, action)
    if not script:
        return
    if broker_required():
        result = module_hook(manifest.id, action, actor="package-center")
        for line in result.stdout.splitlines():
            log("stdout", redact(line))
        for line in result.stderr.splitlines():
            log("stderr", redact(line))
        if result.returncode != 0:
            raise CommandExecutionError(f"{manifest.id}:{action}", result.returncode, result.stderr or result.stdout)
        return
    args = [sys.executable, str(script)] if script.suffix == ".py" else ["/bin/bash", str(script)]
    _run(args, 1800 if action in {"prepare", "rollback", "health"} else 300, log)


def _install_downloaded_package(plan: PackagePlan, manifest: ModuleManifest, log: LogCallback) -> None:
    installation = installation_for(manifest, plan.distribution)
    if not installation or installation.type != InstallationType.download_package or not installation.url or not installation.sha256 or not installation.package_format:
        raise RuntimeError("Downloaded package installation strategy is incomplete")
    request = urllib.request.Request(str(installation.url), headers={"User-Agent": "WebNAS-Package-Center/1"})
    with _shared_temporary_directory("webnas-package-") as temporary:
        package_path = Path(temporary) / f"package.{installation.package_format}"
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(request, timeout=60) as response, package_path.open("wb") as output:  # nosec B310 -- manifest validation requires HTTPS
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 512 * 1024 * 1024:
                    raise RuntimeError("Downloaded package exceeds the 512 MiB safety limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != installation.sha256:
            raise RuntimeError("Downloaded package checksum does not match the trusted manifest")
        log("stdout", f"Verified downloaded {installation.package_format.upper()} package ({size} bytes)")
        command = ["dpkg", "--install", str(package_path)] if installation.package_format == "deb" else ["rpm", "-Uvh", str(package_path)]
        _run(command, 1800, log)


def _rollback_hook(manifest: ModuleManifest, log: LogCallback) -> None:
    if not module_script(manifest.id, "rollback"):
        return
    log("warning", f"Restoring the previous {manifest.name} package state")
    _run_hook(manifest, "rollback", log)
    log("stdout", f"Previous {manifest.name} package state restored")


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
    if manifest.requires_root and hasattr(os, "geteuid") and os.geteuid() != 0 and not broker_required():
        raise PermissionError("Package operations require root or the privileged broker")
    if plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update} and module_script(manifest.id, "prepare"):
        if cancelled():
            raise InterruptedError("Package operation cancelled before repository preparation")
        progress(1, "Prepare trusted package repository")
        _run_hook(manifest, "prepare", log)
    hook_complete = False
    if plan.installation_type == InstallationType.command and plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update}:
        hook_action = "install" if plan.action == PackageAction.reinstall else plan.action.value
        progress(2, f"Run trusted {hook_action} hook")
        _run_hook(manifest, hook_action, log)
        hook_complete = True
    if plan.installation_type == InstallationType.download_package and plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update}:
        progress(2, "Download and verify package")
        _install_downloaded_package(plan, manifest, log)
    if plan.action == PackageAction.uninstall:
        _removable_packages, protected_packages = _partition_uninstall_packages(plan.packages)
        if protected_packages:
            log(
                "warning",
                "Preserving WebNAS runtime packages: " + ", ".join(protected_packages),
            )
    steps = _command_steps(plan, manifest)
    total = max(1, len(steps) + 1)
    for index, (label, args, timeout) in enumerate(steps):
        if cancelled():
            _rollback_hook(manifest, log)
            raise InterruptedError("Package operation cancelled before the next safe step")
        progress(max(1, int(index / total * 90)), label)
        try:
            if args and args[0] == "apt-get":
                _run_apt_command(args, timeout, log)
            elif args and args[0] == "systemctl":
                _run_systemctl_command(args, timeout, log)
            else:
                _run(args, timeout, log)
        except Exception as error:
            try:
                _rollback_hook(manifest, log)
            except Exception as rollback_error:
                raise RuntimeError(f"{label} failed and automatic package rollback also failed: {rollback_error}") from error
            raise
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
        removable_packages, _protected_packages = _partition_uninstall_packages(plan.packages)
        if manager == "apt-get" and shutil.which("dpkg-query"):
            for package in removable_packages:
                result = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], capture_output=True, text=True, timeout=20, check=False, shell=False)
                if result.returncode == 0 and result.stdout.strip().startswith("ii"):
                    raise RuntimeError(f"Package is still installed after removal: {package}")
        elif manager in {"dnf", "yum"} and shutil.which("rpm"):
            for package in removable_packages:
                result = subprocess.run(["rpm", "-q", package], capture_output=True, text=True, timeout=20, check=False, shell=False)
                if result.returncode == 0:
                    raise RuntimeError(f"Package is still installed after removal: {package}")
    progress(100, "Completed")
