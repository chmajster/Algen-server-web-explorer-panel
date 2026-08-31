from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "install" / "install.sh"
STANDARD = REPOSITORY / "install" / "core" / "install-standard.sh"
PORTABLE = REPOSITORY / "install" / "core" / "install-portable.sh"
LOCAL_AUTH = REPOSITORY / "backend" / "app" / "local_auth.py"
BOOTSTRAP_HELPER = REPOSITORY / "scripts" / "consume_local_bootstrap.py"


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
    assert "administrator account chris with password 1" in content
    assert "Change" in content and "password immediately" in content
    assert "PAM and optional LDAP" in content


def test_standard_installer_creates_default_chris_account():
    standard = STANDARD.read_text(encoding="utf-8")
    helper = BOOTSTRAP_HELPER.read_text(encoding="utf-8")

    assert '"$python" "$helper" "chris" "1"' in standard
    assert 'bootstrap_initial_admin' in helper
    assert "Default local administrator created:" in helper
    assert "change the default installer password immediately" in helper


def test_default_password_is_only_an_installer_bootstrap_exception():
    local_auth_source = LOCAL_AUTH.read_text(encoding="utf-8")
    assert "_allow_short_password" in local_auth_source
    assert "Local account password must contain between 12 and 1024 characters" in local_auth_source
    assert "bootstrap_admin" in local_auth_source


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
    assert "Authentication summary" not in result.stdout


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


def test_portable_mode_never_creates_local_bootstrap_credentials():
    portable = PORTABLE.read_text(encoding="utf-8")
    assert '"chris" "1"' not in portable
    assert "Portable authentication mode set to System/PAM" in portable
