from __future__ import annotations

from app.package_center.executor import _partition_uninstall_packages


def test_cifs_utils_is_preserved_during_module_uninstall() -> None:
    removable, protected = _partition_uninstall_packages(
        ["samba", "smbclient", "cifs-utils"]
    )

    assert removable == ["samba", "smbclient"]
    assert protected == ["cifs-utils"]


def test_architecture_qualified_cifs_utils_is_preserved() -> None:
    removable, protected = _partition_uninstall_packages(
        ["samba", "cifs-utils:amd64"]
    )

    assert removable == ["samba"]
    assert protected == ["cifs-utils:amd64"]
