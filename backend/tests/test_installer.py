from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
INSTALLER = REPOSITORY / "install.sh"


def _bash() -> str:
    if os.name == "nt":
        pytest.skip("installer behavior requires a native Linux Bash environment")
    executable = shutil.which("bash")
    if not executable:
        pytest.skip("bash is unavailable")
    return executable


def _functions() -> str:
    content = INSTALLER.read_text(encoding="utf-8")
    functions, marker, _ = content.rpartition('\nmain "$@"')
    assert marker
    return functions


def _run_harness(tmp_path: Path, commands: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash()],
        input=f"{_functions()}\ntrap - ERR\n{textwrap.dedent(commands)}",
        cwd=REPOSITORY,
        env={**os.environ, "TEST_ROOT": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_installer_has_valid_bash_syntax():
    result = subprocess.run([_bash(), "-n", str(INSTALLER)], capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr


def test_existing_install_defaults_to_update_after_timeout_and_keeps_config(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        INSTALL_DIR="$TEST_ROOT/app"
        CONFIG_DIR="$TEST_ROOT/etc"
        CONFIG_FILE="$CONFIG_DIR/config.yaml"
        mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
        printf 'server:\n  port: 8123\n' > "$CONFIG_FILE"
        PORT=5000
        PORT_EXPLICIT=no
        SERVICE_USER_EXPLICIT=yes
        ASSUME_YES=no
        EXISTING_ACTION=""
        read_from_tty_timeout() { return 1; }
        handle_existing_installation >/dev/null
        [[ "$ACTION" == "update" ]]
        [[ "$UPDATE_CONFIG" == "no" ]]
        [[ "$PORT" == "8123" ]]
        """,
    )
    assert result.returncode == 0, result.stderr


def test_reinstall_creates_backup_and_removes_only_application_files(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        INSTALL_DIR="$TEST_ROOT/app"
        CONFIG_DIR="$TEST_ROOT/etc"
        CONFIG_FILE="$CONFIG_DIR/config.yaml"
        DATA_DIR="$TEST_ROOT/data"
        LOG_DIR="$TEST_ROOT/log"
        BACKUP_ROOT="$TEST_ROOT/backups"
        SERVICE_FILE="$TEST_ROOT/webnas.service"
        PAM_SERVICE_FILE="$TEST_ROOT/webnas.pam"
        mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
        printf 'old app\n' > "$INSTALL_DIR/version.txt"
        printf 'server:\n  port: 5000\n' > "$CONFIG_FILE"
        printf 'database\n' > "$DATA_DIR/state.db"
        printf 'log\n' > "$LOG_DIR/webnas.log"
        printf 'service\n' > "$SERVICE_FILE"
        printf 'pam\n' > "$PAM_SERVICE_FILE"
        rsync() {
          [[ "$1" != "-a" ]] || shift
          local source="${1%/}"
          local target="$2"
          mkdir -p "$target"
          cp -a "$source/." "$target/"
        }
        ACTION=reinstall
        backup_before_application_change >/dev/null
        [[ -f "$LAST_BACKUP_DIR/config.yaml" ]]
        [[ -f "$LAST_BACKUP_DIR/app/version.txt" ]]
        [[ -f "$LAST_BACKUP_DIR/webnas.service" ]]
        [[ -f "$LAST_BACKUP_DIR/webnas.pam" ]]
        remove_existing_installation >/dev/null
        [[ ! -e "$INSTALL_DIR" ]]
        [[ -f "$CONFIG_FILE" ]]
        [[ -f "$DATA_DIR/state.db" ]]
        [[ -f "$LOG_DIR/webnas.log" ]]
        mkdir -p "$INSTALL_DIR"
        printf 'partial reinstall\n' > "$INSTALL_DIR/partial.txt"
        printf 'server:\n  port: 9999\n' > "$CONFIG_FILE"
        APP_COPY_STARTED=yes
        SERVICE_WAS_ACTIVE=no
        systemctl() { return 0; }
        restore_failed_reinstall >/dev/null
        [[ -f "$INSTALL_DIR/version.txt" ]]
        [[ ! -f "$INSTALL_DIR/partial.txt" ]]
        grep -q 'port: 5000' "$CONFIG_FILE"
        """,
    )
    assert result.returncode == 0, result.stderr


def test_reinstall_is_a_supported_non_interactive_action(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        parse_args --existing-action reinstall --yes
        [[ "$EXISTING_ACTION" == "reinstall" ]]
        [[ "$ASSUME_YES" == "yes" ]]
        [[ "$NON_INTERACTIVE" == "yes" ]]
        """,
    )
    assert result.returncode == 0, result.stderr


def test_proxmox_enterprise_source_fallback_is_temporary(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        APT_SOURCES_ROOT="$TEST_ROOT/apt"
        mkdir -p "$APT_SOURCES_ROOT/sources.list.d"
        printf 'deb http://deb.debian.org/debian bookworm main\n' > "$APT_SOURCES_ROOT/sources.list"
        printf 'deb https://enterprise.proxmox.com/debian/pve bookworm pve-enterprise\n' > "$APT_SOURCES_ROOT/sources.list.d/pve-enterprise.list"
        printf 'deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription\n' > "$APT_SOURCES_ROOT/sources.list.d/pve-community.list"
        prepare_apt_sources_without_proxmox_enterprise
        ! grep -Rqi 'enterprise.proxmox.com' "$APT_TEMP_DIR"
        grep -Rqi 'deb.debian.org' "$APT_TEMP_DIR"
        grep -Rqi 'pve-no-subscription' "$APT_TEMP_DIR"
        grep -qi 'enterprise.proxmox.com' "$APT_SOURCES_ROOT/sources.list.d/pve-enterprise.list"
        cleanup
        """,
    )
    assert result.returncode == 0, result.stderr


def test_installer_bootstraps_only_missing_download_tools_before_source_download(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        PKG_MANAGER=apt
        installed=no
        calls="$TEST_ROOT/calls"
        refresh_apt_metadata() { printf 'refresh\n' >> "$calls"; }
        apt_get() {
          printf '%s\n' "$*" >> "$calls"
          installed=yes
        }
        command() {
          if [[ "$1" == "-v" ]]; then
            if [[ "$installed" == "yes" ]]; then
              return 0
            fi
            case "$2" in
              curl|tar|rsync) return 1 ;;
              wget) return 0 ;;
            esac
          fi
          builtin command "$@"
        }
        ensure_download_tools >/dev/null
        grep -qx 'refresh' "$calls"
        grep -qx 'install -y curl tar rsync' "$calls"
        ! grep -q 'wget' "$calls"
        """,
    )
    assert result.returncode == 0, result.stderr


def test_installer_skips_bootstrap_when_curl_wget_tar_and_rsync_exist(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        PKG_MANAGER=apt
        refresh_apt_metadata() { return 99; }
        apt_get() { return 99; }
        ensure_download_tools >/dev/null
        """,
    )
    assert result.returncode == 0, result.stderr
