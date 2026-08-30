from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "install.sh"
STANDARD = REPOSITORY / "install-standard.sh"
PORTABLE = REPOSITORY / "install-portable.sh"
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
    assert "shown\nonce" in content
    assert "never written to a plaintext credential\nfile" in content
    assert "PAM and optional LDAP" in content
    assert "Settings ->\nAdministration -> Authentication" in content


def test_standard_installer_initializes_and_prints_bootstrap_once():
    standard = STANDARD.read_text(encoding="utf-8")
    helper = BOOTSTRAP_HELPER.read_text(encoding="utf-8")

    assert "/api/auth/config" in standard
    assert "consume_local_bootstrap.py" in standard
    assert 'runuser -u "$SERVICE_USER"' in standard
    assert "Initial local administrator credentials:" in helper
    assert "displayed once and is not stored in plaintext" in helper


def test_bootstrap_password_has_no_plaintext_file_storage():
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (LAUNCHER, STANDARD, PORTABLE, LOCAL_AUTH, BOOTSTRAP_HELPER)
    )

    assert "initial-local-admin.txt" not in sources
    assert "bootstrap_path" not in LOCAL_AUTH.read_text(encoding="utf-8")
    assert "secrets_service().save" in LOCAL_AUTH.read_text(encoding="utf-8")
    assert "bootstrap_secret_id" in LOCAL_AUTH.read_text(encoding="utf-8")


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
    local_auth = LOCAL_AUTH.read_text(encoding="utf-8")

    assert "initial-local-admin.txt" not in portable
    assert 'if self.auth_mode() == "local":' in local_auth
