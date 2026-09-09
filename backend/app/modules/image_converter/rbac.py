"""Image Converter permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

IMAGE_CONVERTER_VIEW = "image_converter.view"
IMAGE_CONVERTER_CONVERT = "image_converter.convert"


def register_permissions() -> None:
    permissions = {
        IMAGE_CONVERTER_VIEW: ("view", PermissionRisk.low, False),
        IMAGE_CONVERTER_CONVERT: ("convert", PermissionRisk.medium, True),
    }
    for permission, (operation, risk, mutating) in permissions.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(
                id=permission,
                category="image_converter",
                operation=operation,
                applications=["module:image-converter"],
                risk=risk,
                mutating=mutating,
                label_key=f"permissions.{permission}",
                description_key="permissions.category.image_converter.description",
            )
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(permissions)
    ROLE_PERMISSIONS[Role.operator].update(permissions)
    ROLE_PERMISSIONS[Role.auditor].add(IMAGE_CONVERTER_VIEW)


register_permissions()
