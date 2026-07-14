from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

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


def redact(line: str) -> str:
    return SECRET_RE.sub(r"\1\2[REDACTED]", line.replace("\x00", ""))[-4000:]


def _command_steps(plan: PackagePlan, manifest: ModuleManifest) -> list[tuple[str, list[str], int]]:
    manager = plan.distribution.package_manager
    packages = plan.packages
    steps: list[tuple[str, list[str], int]] = []
    if plan.action in {PackageAction.install, PackageAction.update}:
        if manager == "apt-get":
            steps.append(("Refresh package metadata", ["apt-get", "update"], 900))
            steps.append(("Install packages", ["apt-get", "install", "-y", "--no-install-recommends", *packages], 1800))
        elif manager in {"dnf", "yum"}:
            steps.append(("Install packages", [manager, "install", "-y", *packages], 1800))
        steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
        for service in manifest.systemd_services:
            steps.append((f"Enable {service}", ["systemctl", "enable", service], 120))
            steps.append((f"Start {service}", ["systemctl", "start", service], 180))
    elif plan.action == PackageAction.uninstall:
        for service in reversed(manifest.systemd_services):
            steps.append((f"Stop {service}", ["systemctl", "stop", service], 180))
            steps.append((f"Disable {service}", ["systemctl", "disable", service], 120))
        if manager == "apt-get":
            steps.append(("Remove packages", ["apt-get", "remove", "-y", *packages], 1800))
        elif manager in {"dnf", "yum"}:
            steps.append(("Remove packages", [manager, "remove", "-y", *packages], 1800))
        steps.append(("Reload systemd units", ["systemctl", "daemon-reload"], 120))
    elif plan.action in {PackageAction.start, PackageAction.stop, PackageAction.restart}:
        for service in manifest.systemd_services:
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

    def drain(stream, name: str) -> None:
        if stream is None:
            return
        for line in stream:
            log(name, redact(line.rstrip()))

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
        raise RuntimeError(f"{Path(args[0]).name} failed with exit code {code}")


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
        _run(args, timeout, log)
        if label in {"Install packages", "Remove packages"} and plan.action in {PackageAction.install, PackageAction.update, PackageAction.uninstall}:
            progress(max(1, int((index + 0.5) / total * 90)), f"Run trusted {plan.action.value} hook")
            _run_hook(manifest, plan.action.value, log)
            hook_complete = True
    if plan.action in {PackageAction.install, PackageAction.update, PackageAction.uninstall} and not hook_complete:
        progress(92, f"Run trusted {plan.action.value} hook")
        _run_hook(manifest, plan.action.value, log)
    if plan.action == PackageAction.uninstall and plan.remove_data:
        progress(96, "Remove module data")
        _remove_data(manifest, log)
    if plan.action in {PackageAction.install, PackageAction.update} and manifest.healthcheck:
        progress(97, "Run health check")
        _run_hook(manifest, "health", log)
    progress(100, "Completed")
