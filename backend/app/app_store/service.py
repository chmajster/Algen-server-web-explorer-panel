from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml
from fastapi import HTTPException

from ..proxmox_guard import safe_mode_active


MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"


def load_manifest(app_id: str) -> dict:
    path = MODULES_DIR / app_id / "manifest.yaml"
    if not path.exists():
        raise HTTPException(404, "App module not found")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def all_manifests() -> list[dict]:
    result = []
    for path in sorted(MODULES_DIR.glob("*/manifest.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifest["id"] = path.parent.name
        result.append(manifest)
    return result


def service_status(service: str) -> str:
    executable = shutil.which("systemctl")
    if not executable:
        return "unsupported"
    result = subprocess.run([executable, "is-active", service], capture_output=True, text=True, timeout=3, check=False, shell=False)
    return result.stdout.strip() or "unknown"


def plan_install(app_id: str) -> list[str]:
    manifest = load_manifest(app_id)
    if app_id == "samba" and not shutil.which("apt-get"):
        return ["Samba module requires apt-get on Debian/Ubuntu-like systems."]
    steps = [f"Install packages: {', '.join(manifest.get('apt_packages', []))}"]
    steps += [f"Enable/start service: {service}" for service in manifest.get("systemd_services", [])]
    return steps


def assert_app_allowed_on_host(app_id: str) -> None:
    manifest = load_manifest(app_id)
    if safe_mode_active() and not manifest.get("proxmox_safe", False):
        raise HTTPException(403, "Module is blocked by Proxmox Safe Mode")


def run_service(app_id: str, action: str) -> None:
    manifest = load_manifest(app_id)
    for service in manifest.get("systemd_services", []):
        executable = shutil.which("systemctl") or "systemctl"
        result = subprocess.run([executable, action, service], capture_output=True, text=True, timeout=600, check=False, shell=False)
        if result.returncode != 0:
            raise HTTPException(400, result.stderr.strip() or result.stdout.strip() or f"systemctl {action} failed")
