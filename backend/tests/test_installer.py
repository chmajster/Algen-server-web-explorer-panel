from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
INSTALLER = REPOSITORY / "install.sh"
UNINSTALLER = REPOSITORY / "uninstall.sh"


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


def test_installer_prompts_use_interactive_stdin_before_dev_tty():
    installer = INSTALLER.read_text(encoding="utf-8")
    prompt_reader = installer.split("read_from_tty() {", 1)[1].split("\n}", 1)[0]
    timeout_reader = installer.split("read_from_tty_timeout() {", 1)[1].split("\n}", 1)[0]

    assert "[[ -t 0 ]]" in prompt_reader
    assert "exec {tty_fd}<>/dev/tty 2>/dev/null" in prompt_reader
    assert "[[ -t 0 ]]" in timeout_reader
    assert "exec {tty_fd}<>/dev/tty 2>/dev/null" in timeout_reader


def test_update_prepares_an_isolated_release_without_stopping_the_active_service():
    installer = INSTALLER.read_text(encoding="utf-8")
    main = installer.split("main() {", 1)[1].split('\nmain "$@"', 1)[0]

    assert "prepare_release" in main
    assert 'systemctl stop "$SERVICE_NAME"' not in main
    assert 'release_dir="${application_root}/releases/${release_id}"' in installer
    assert "webnas_release.py" in installer
    assert "NEEDRESTART_MODE=l" in installer


def test_installer_prints_a_final_status_and_preserves_the_exit_code(tmp_path):
    success = _run_harness(
        tmp_path,
        """
        cleanup() { return 0; }
        ACTION=update
        INSTALL_COMPLETED=yes
        exit 0
        """,
    )
    assert success.returncode == 0, success.stderr
    assert "[STATUS: OK] Aktualizacja zakończona pomyślnie." in success.stdout

    failure = _run_harness(
        tmp_path,
        """
        cleanup_failed_install() { return 0; }
        ACTION=reinstall
        CURRENT_STEP="Frontend build"
        exit 23
        """,
    )
    assert failure.returncode == 23
    assert "[STATUS: BŁĄD] Wystąpił błąd podczas operacji: Ponowna instalacja." in failure.stderr
    assert "Etap: Frontend build | kod wyjścia: 23" in failure.stderr


def test_node_version_check_accepts_supported_node_22_without_evaluating_javascript(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        mkdir -p "$TEST_ROOT/bin"
        cat > "$TEST_ROOT/bin/node" <<'NODE'
#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'v22.23.1\n'
  exit 0
fi
printf 'JavaScript execution is disabled\n' >&2
exit 77
NODE
        chmod +x "$TEST_ROOT/bin/node"
        PATH="$TEST_ROOT/bin:$PATH"
        node_version_ok
        """,
    )
    assert result.returncode == 0, result.stderr


def test_node_version_check_rejects_node_22_before_minimum_version(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        mkdir -p "$TEST_ROOT/bin"
        cat > "$TEST_ROOT/bin/node" <<'NODE'
#!/bin/sh
printf 'v22.11.0\n'
NODE
        chmod +x "$TEST_ROOT/bin/node"
        PATH="$TEST_ROOT/bin:$PATH"
        ! node_version_ok
        """,
    )
    assert result.returncode == 0, result.stderr


def test_frontend_build_offers_audit_fix_and_defaults_to_no(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        INSTALL_DIR="$TEST_ROOT/app"
        SERVICE_USER=webnas
        SERVICE_USER_GROUP=webnas
        mkdir -p "$INSTALL_DIR/frontend" "$INSTALL_DIR/scripts"
        cp scripts/verify_frontend_build.py "$INSTALL_DIR/scripts/verify_frontend_build.py"
        calls="$TEST_ROOT/npm-calls"
        npm() {
          printf '%s\n' "$*" >> "$calls"
          if [[ "$1" == "audit" && "$2" == "--json" ]]; then
            printf '{"metadata":{"vulnerabilities":{"total":2}}}\n'
            return 1
          fi
          if [[ "$1" == "run" && "$2" == "build" ]]; then
            mkdir -p "$INSTALL_DIR/frontend/dist.next/assets"
            printf '<script src="/assets/app-hash.js"></script>\n' > "$INSTALL_DIR/frontend/dist.next/index.html"
            printf '// /api/modules/hosts-manager/enrollment-tokens apmid_id\n' > "$INSTALL_DIR/frontend/dist.next/assets/app-hash.js"
          fi
        }
        confirm_npm_audit_fix() { return 1; }
        chown() { return 0; }
        build_frontend >/dev/null
        grep -qx 'ci' "$calls"
        grep -qx 'audit --json' "$calls"
        grep -qx 'run build -- --outDir dist.next' "$calls"
        ! grep -qx 'audit fix' "$calls"
        grep -q '/assets/app-hash.js' "$INSTALL_DIR/frontend/dist/index.html"
        test -f "$INSTALL_DIR/frontend/dist/assets/app-hash.js"
        """,
    )
    assert result.returncode == 0, result.stderr


def test_frontend_build_rejects_skip_build_to_prevent_a_stale_bundle(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        INSTALL_DIR="$TEST_ROOT/app"
        SKIP_BUILD=yes
        mkdir -p "$INSTALL_DIR/frontend/dist"
        printf 'old bundle\n' > "$INSTALL_DIR/frontend/dist/index.html"
        build_frontend
        """,
    )
    assert result.returncode != 0
    assert "incompatible frontend bundle" in result.stdout + result.stderr


def test_frontend_build_runs_audit_fix_only_after_confirmation(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        INSTALL_DIR="$TEST_ROOT/app"
        SERVICE_USER=webnas
        SERVICE_USER_GROUP=webnas
        mkdir -p "$INSTALL_DIR/frontend" "$INSTALL_DIR/scripts"
        cp scripts/verify_frontend_build.py "$INSTALL_DIR/scripts/verify_frontend_build.py"
        calls="$TEST_ROOT/npm-calls"
        npm() {
          printf '%s\n' "$*" >> "$calls"
          if [[ "$1" == "audit" && "$2" == "--json" ]]; then
            printf '{"metadata":{"vulnerabilities":{"total":2}}}\n'
            return 1
          fi
          if [[ "$1" == "run" && "$2" == "build" ]]; then
            mkdir -p "$INSTALL_DIR/frontend/dist.next/assets"
            printf '<script src="/assets/app-hash.js"></script>\n' > "$INSTALL_DIR/frontend/dist.next/index.html"
            printf '// /api/modules/hosts-manager/enrollment-tokens apmid_id\n' > "$INSTALL_DIR/frontend/dist.next/assets/app-hash.js"
          fi
        }
        confirm_npm_audit_fix() { return 0; }
        chown() { return 0; }
        build_frontend >/dev/null
        grep -qx 'audit fix' "$calls"
        grep -qx 'run build -- --outDir dist.next' "$calls"
        """,
    )
    assert result.returncode == 0, result.stderr


def test_installer_wires_usb_udev_events_to_a_device_bound_systemd_service():
    installer = INSTALLER.read_text(encoding="utf-8")
    uninstaller = UNINSTALLER.read_text(encoding="utf-8")
    rule = (REPOSITORY / "packaging" / "99-webnas-usb-automount.rules").read_text(encoding="utf-8")

    assert 'ENV{ID_BUS}=="usb"' in rule
    assert 'ENV{ID_FS_USAGE}=="filesystem"' in rule
    assert 'ENV{SYSTEMD_WANTS}+="webnas-usb-mount@%k.service"' in rule
    assert "BindsTo=dev-%i.device" in installer
    assert "RuntimeDirectory=webnas" in installer
    assert "usb_automount.py mount /dev/%I" in installer
    assert "usb_automount.py unmount /dev/%I" in installer
    assert 'rm -f "$USB_SERVICE_FILE" "$USB_UDEV_RULE_FILE"' in uninstaller


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


def test_installer_enables_python314_ppa_on_ubuntu_2404(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        WEBNAS_OS_RELEASE_FILE="$TEST_ROOT/os-release"
        printf 'ID=ubuntu\nVERSION_CODENAME=noble\n' > "$WEBNAS_OS_RELEASE_FILE"
        calls="$TEST_ROOT/calls"
        python_packages_available=no
        apt_cache() { [[ "$python_packages_available" == "yes" ]]; }
        apt_get() { printf 'apt-get %s\n' "$*" >> "$calls"; }
        refresh_apt_metadata() { printf 'apt-update\n' >> "$calls"; }
        add-apt-repository() {
          printf 'add-repository %s\n' "$*" >> "$calls"
          python_packages_available=yes
        }
        command() {
          [[ "$1" == "-v" && "$2" == "add-apt-repository" ]] && return 0
          builtin command "$@"
        }
        ensure_python314_apt_repository >/dev/null
        grep -qx 'apt-get install -y software-properties-common ca-certificates' "$calls"
        grep -qx 'add-repository -y -n ppa:deadsnakes/ppa' "$calls"
        grep -qx 'apt-update' "$calls"
        """,
    )
    assert result.returncode == 0, result.stderr


def test_installer_keeps_configured_python314_repository(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        apt_cache() { return 0; }
        apt_get() { return 99; }
        refresh_apt_metadata() { return 99; }
        add-apt-repository() { return 99; }
        ensure_python314_apt_repository
        """,
    )
    assert result.returncode == 0, result.stderr


def test_installer_does_not_add_ubuntu_ppa_on_debian(tmp_path):
    result = _run_harness(
        tmp_path,
        r"""
        WEBNAS_OS_RELEASE_FILE="$TEST_ROOT/os-release"
        printf 'ID=debian\nVERSION_CODENAME=bookworm\n' > "$WEBNAS_OS_RELEASE_FILE"
        apt_cache() { return 1; }
        ensure_python314_apt_repository
        """,
    )
    assert result.returncode != 0
    assert "Python 3.14 packages are unavailable for debian bookworm" in result.stdout
