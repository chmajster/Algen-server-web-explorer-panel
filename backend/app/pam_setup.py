from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Mapping


MANAGED_HEADER = "# Managed by WebNAS installer. Local changes below this marker may be replaced."
PAM_SERVICE_PATH = Path("/etc/pam.d/webnas")
OS_RELEASE_PATH = Path("/etc/os-release")


def _parse_os_release(path: Path = OS_RELEASE_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _distribution_family(os_release: Mapping[str, str]) -> str:
    identifiers = {
        item.casefold()
        for item in (
            os_release.get("ID", ""),
            *os_release.get("ID_LIKE", "").split(),
        )
        if item
    }
    if identifiers & {"debian", "ubuntu"}:
        return "debian"
    if identifiers & {"rhel", "fedora", "centos", "rocky", "almalinux", "ol"}:
        return "rhel"
    if identifiers & {"suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles"}:
        return "suse"
    raise RuntimeError("Unsupported Linux distribution for WebNAS PAM configuration")


def render_webnas_pam(os_release: Mapping[str, str]) -> str:
    family = _distribution_family(os_release)
    if family == "debian":
        body = """@include common-auth
@include common-account
@include common-password
@include common-session
"""
    elif family == "rhel":
        body = """auth       include      system-auth
account    include      system-auth
password   include      system-auth
session    include      system-auth
"""
    else:
        body = """auth       include      common-auth
account    include      common-account
password   include      common-password
session    include      common-session
"""
    return f"#%PAM-1.0\n{MANAGED_HEADER}\n{body}"


def ensure_webnas_pam_service(
    *,
    target: Path = PAM_SERVICE_PATH,
    os_release_path: Path = OS_RELEASE_PATH,
    force_managed_update: bool = True,
) -> bool:
    """Install the dedicated PAM service used by WebNAS.

    Existing administrator-owned PAM files are not overwritten. Files carrying
    the WebNAS managed marker are upgraded atomically when the distro template
    changes. Returns True when the file was created or replaced.
    """

    content = render_webnas_pam(_parse_os_release(os_release_path))
    if target.exists():
        try:
            current = target.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise RuntimeError(f"Cannot read existing PAM service file: {target}") from error
        if current == content:
            return False
        if MANAGED_HEADER not in current:
            # Preserve an explicitly administrator-managed service. Its
            # existence is enough for the runtime provider; validation remains
            # the administrator's responsibility.
            return False
        if not force_managed_update:
            return False

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".webnas-pam-", dir=str(target.parent), text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return True
