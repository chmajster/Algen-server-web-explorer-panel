from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = (ROOT / "install-standard.sh").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "install.sh").read_text(encoding="utf-8")
RUNTIME_HELPER = (ROOT / "scripts" / "install_python314_runtime.sh").read_text(encoding="utf-8")


def test_python_source_is_pinned_to_official_3147_tarball() -> None:
    assert 'PYTHON_REQUIRED_MAJOR_MINOR="3.14"' in RUNTIME_HELPER
    assert 'PYTHON_SOURCE_VERSION="3.14.7"' in RUNTIME_HELPER
    assert (
        'PYTHON_SOURCE_SHA256="3b48dac8fb59f62eaa67ac83c1eb12bda1b7a08406dd286e252c11a66be27f81"'
        in RUNTIME_HELPER
    )
    assert "https://www.python.org/ftp/python/${PYTHON_SOURCE_VERSION}/Python-${PYTHON_SOURCE_VERSION}.tar.xz" in RUNTIME_HELPER
    assert "sha256sum --check --status" in RUNTIME_HELPER
    assert "--proto '=https'" in RUNTIME_HELPER


def test_debian_runtime_is_private_and_does_not_modify_system_python() -> None:
    assert 'PYTHON_RUNTIME_ROOT="${WEBNAS_APPLICATION_ROOT}/runtime/python"' in RUNTIME_HELPER
    assert 'PYTHON_RUNTIME_BIN="${PYTHON_RUNTIME_DIR}/bin/python3.14"' in RUNTIME_HELPER
    assert "make -C \"$source_dir\" altinstall" in RUNTIME_HELPER
    assert "make -C \"$source_dir\" install" not in RUNTIME_HELPER
    assert "update-alternatives" not in RUNTIME_HELPER
    assert "/usr/bin/python3.14" not in RUNTIME_HELPER
    assert "--break-system-packages" not in RUNTIME_HELPER
    assert "/etc/profile" not in RUNTIME_HELPER
    assert "/etc/environment" not in RUNTIME_HELPER
    assert "readlink -f /usr/bin/python3" in RUNTIME_HELPER
    assert "apt-get --version" in RUNTIME_HELPER
    assert "dpkg --audit" in RUNTIME_HELPER


def test_debian_path_never_enables_ubuntu_or_unstable_python_repositories() -> None:
    lowered = RUNTIME_HELPER.lower()
    for forbidden in ("deadsnakes", "forky", "update-alternatives"):
        assert forbidden not in lowered
    assert "ppa:" not in lowered
    assert "sources.list" not in lowered
    assert "apt full-upgrade" not in lowered
    assert "apt dist-upgrade" not in lowered


def test_debian_trixie_detection_uses_os_release_fields() -> None:
    assert 'INSTALLER_DISTRO_ID="$(os_release_value ID || true)"' in RUNTIME_HELPER
    assert 'INSTALLER_DISTRO_VERSION_ID="$(os_release_value VERSION_ID || true)"' in RUNTIME_HELPER
    assert 'INSTALLER_DISTRO_CODENAME="$(os_release_value VERSION_CODENAME || true)"' in RUNTIME_HELPER
    assert '"$INSTALLER_DISTRO_ID" == "debian"' in RUNTIME_HELPER
    assert '"$INSTALLER_DISTRO_VERSION_ID" == "13"' in RUNTIME_HELPER
    assert '"$INSTALLER_DISTRO_CODENAME" == "trixie"' in RUNTIME_HELPER


def test_existing_private_runtime_is_checked_before_building() -> None:
    private_check = RUNTIME_HELPER.index('if verify_python314 "$PYTHON_RUNTIME_BIN"; then')
    source_build = RUNTIME_HELPER.index("install_python314_debian_source")
    assert private_check < source_build
    assert 'candidate="$(command -v python3.14 2>/dev/null || true)"' in RUNTIME_HELPER
    assert 'ok "Reusing WebNAS Python runtime: ${PYTHON_BIN}"' in RUNTIME_HELPER


def test_source_build_has_safe_cleanup_and_supported_architectures() -> None:
    assert "mktemp -d -t webnas-python314.XXXXXX" in RUNTIME_HELPER
    assert "safe_remove_python314_path" in RUNTIME_HELPER
    assert '/tmp/webnas-python314.*|/var/tmp/webnas-python314.*|"$PYTHON_RUNTIME_DIR"' in RUNTIME_HELPER
    assert "/|/usr|/usr/*|/opt|/etc|/var" in RUNTIME_HELPER
    assert "x86_64|aarch64" in RUNTIME_HELPER
    assert "(( jobs > 4 )) && jobs=\"4\"" in RUNTIME_HELPER


def test_runtime_standard_library_capabilities_are_validated() -> None:
    for module in ("bz2", "ctypes", "lzma", "readline", "sqlite3", "ssl", "venv", "zlib"):
        assert f"import {module}" in RUNTIME_HELPER


def test_virtualenv_and_pip_use_selected_python314() -> None:
    assert '"$PYTHON_BIN" -m venv "${INSTALL_DIR}/backend/.venv"' in RUNTIME_HELPER
    assert 'local venv_python="${INSTALL_DIR}/backend/.venv/bin/python"' in RUNTIME_HELPER
    assert 'verify_python314 "$venv_python"' in RUNTIME_HELPER
    assert '"$venv_python" -m pip install --upgrade pip wheel' in RUNTIME_HELPER
    assert '"$venv_python" -m pip install -r "${INSTALL_DIR}/backend/requirements.txt"' in RUNTIME_HELPER


def test_standard_installer_loads_runtime_helper_before_dependencies() -> None:
    helper_load = INSTALLER.index('source "${SOURCE_DIR}/scripts/install_python314_runtime.sh"')
    dependency_install = INSTALLER.rindex("  install_dependencies\n")
    assert helper_load < dependency_install
    assert '[[ -f "${SOURCE_DIR}/scripts/install_python314_runtime.sh" ]]' in INSTALLER


def test_clean_reinstall_preserves_persistent_runtime_directory() -> None:
    assert "current|releases|runtime|uninstall.sh|webnas_release.py) continue ;;" in LAUNCHER
