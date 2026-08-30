from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "install.sh"
PORTABLE = REPOSITORY / "install-portable.sh"


def _bash() -> str:
    if os.name == "nt":
        pytest.skip("installer behavior requires a native Linux Bash environment")
    executable = shutil.which("bash")
    if not executable:
        pytest.skip("bash is unavailable")
    return executable


def test_launcher_documents_local_database_as_standard_default():
    content = LAUNCHER.read_text(encoding="utf-8")

    assert "Local database authentication mode" in content
    assert "PAM and optional LDAP" in content
    assert "Settings -> Administration -> Authentication" in content


def test_launcher_initializes_and_reports_local_authentication_after_install():
    content = LAUNCHER.read_text(encoding="utf-8")

    assert "/api/auth/config" in content
    assert "/var/lib/webnas/initial-local-admin.txt" in content
    assert "Initial local administrator credentials" in content
    assert "deleted after the first successful local login" in content


def test_launcher_preserves_standard_installer_failure_status(tmp_path: Path):
    launcher = tmp_path / "install.sh"
    standard = tmp_path / "install-standard.sh"
    shutil.copy2(LAUNCHER, launcher)
    standard.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")

    result = subprocess.run(
        [_bash(), str(launcher), "--yes"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 23
    assert "Authentication mode" not in result.stdout


def test_launcher_skips_authentication_summary_for_non_runtime_actions():
    content = LAUNCHER.read_text(encoding="utf-8")
    function = content.split("standard_action_has_runtime() {", 1)[1].split("\n}", 1)[0]

    for action in ("backup-config", "remove", "remove-app", "remove-all", "abort"):
        assert action in function


def test_portable_mode_explicitly_uses_system_pam_authentication():
    content = PORTABLE.read_text(encoding="utf-8")

    assert "Portable authentication mode set to System/PAM" in content
    assert "VALUES(1,'system',0,'portable-installer')" in content
    assert "auth:\n  provider: pam" in content
    assert "portable mode does not provision Local POSIX companions" in content


def test_portable_mode_does_not_expose_unused_local_bootstrap_secret():
    content = PORTABLE.read_text(encoding="utf-8")

    assert 'rm -f -- "${WORK_DIR}/runtime/data/initial-local-admin.txt"' in content
