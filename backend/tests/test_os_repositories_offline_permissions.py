from __future__ import annotations

from app.identity.models import Role
from app.identity.permissions import PERMISSION_REGISTRY, ROLE_PERMISSIONS
from app.modules.os_repositories.offline_permissions import (
    OFFLINE_AIRGAP_MANAGE,
    OFFLINE_CONFIGURE,
    OFFLINE_DELETE,
    OFFLINE_EXPORT,
    OFFLINE_IMPORT,
    OFFLINE_VIEW,
    register_offline_repository_permissions,
)


def test_offline_repository_permissions_are_registered_with_expected_roles():
    register_offline_repository_permissions()

    assert OFFLINE_VIEW in PERMISSION_REGISTRY
    assert OFFLINE_EXPORT in PERMISSION_REGISTRY
    assert OFFLINE_IMPORT in PERMISSION_REGISTRY
    assert OFFLINE_DELETE in PERMISSION_REGISTRY
    assert OFFLINE_AIRGAP_MANAGE in PERMISSION_REGISTRY

    assert OFFLINE_VIEW in ROLE_PERMISSIONS[Role.auditor]
    assert OFFLINE_EXPORT not in ROLE_PERMISSIONS[Role.auditor]

    assert OFFLINE_VIEW in ROLE_PERMISSIONS[Role.operator]
    assert OFFLINE_EXPORT in ROLE_PERMISSIONS[Role.operator]
    assert OFFLINE_IMPORT in ROLE_PERMISSIONS[Role.operator]
    assert OFFLINE_CONFIGURE in ROLE_PERMISSIONS[Role.operator]
    assert OFFLINE_DELETE not in ROLE_PERMISSIONS[Role.operator]
    assert OFFLINE_AIRGAP_MANAGE not in ROLE_PERMISSIONS[Role.operator]

    assert OFFLINE_DELETE in ROLE_PERMISSIONS[Role.admin]
    assert OFFLINE_AIRGAP_MANAGE in ROLE_PERMISSIONS[Role.admin]
