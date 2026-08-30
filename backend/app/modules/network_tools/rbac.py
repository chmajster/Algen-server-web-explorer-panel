"""Network Tools permissions registered in the shared Identity registry."""

from __future__ import annotations

from ...identity.models import PermissionMetadata, PermissionRisk, Role
from ...identity.permissions import ALL_PERMISSIONS, PERMISSION_REGISTRY, ROLE_PERMISSIONS

NETWORK_TOOLS_VIEW = "network_tools.view"
NETWORK_TOOLS_PING = "network_tools.ping"
NETWORK_TOOLS_TRACEROUTE = "network_tools.traceroute"
NETWORK_TOOLS_DNS = "network_tools.dns"
NETWORK_TOOLS_PORT_TEST = "network_tools.port_test"
NETWORK_TOOLS_HTTP_TEST = "network_tools.http_test"
NETWORK_TOOLS_ROUTES = "network_tools.routes"
NETWORK_TOOLS_CONNECTIONS = "network_tools.connections"

_PERMISSIONS = {
    NETWORK_TOOLS_VIEW: ("view", PermissionRisk.low, False),
    NETWORK_TOOLS_PING: ("ping", PermissionRisk.low, False),
    NETWORK_TOOLS_TRACEROUTE: ("traceroute", PermissionRisk.low, False),
    NETWORK_TOOLS_DNS: ("dns", PermissionRisk.low, False),
    NETWORK_TOOLS_PORT_TEST: ("port_test", PermissionRisk.low, False),
    NETWORK_TOOLS_HTTP_TEST: ("http_test", PermissionRisk.medium, False),
    NETWORK_TOOLS_ROUTES: ("routes", PermissionRisk.low, False),
    NETWORK_TOOLS_CONNECTIONS: ("connections", PermissionRisk.low, False),
}


def register_permissions() -> None:
    for permission, (operation, risk, mutating) in _PERMISSIONS.items():
        if permission not in PERMISSION_REGISTRY:
            PERMISSION_REGISTRY[permission] = PermissionMetadata(id=permission, category="network_tools", operation=operation, applications=["module:network-tools"], risk=risk, mutating=mutating, label_key=f"permissions.{permission}", description_key="permissions.category.network_tools.description")
        ALL_PERMISSIONS.add(permission)
    ROLE_PERMISSIONS[Role.admin].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.operator].update(_PERMISSIONS)
    ROLE_PERMISSIONS[Role.auditor].update({NETWORK_TOOLS_VIEW, NETWORK_TOOLS_DNS, NETWORK_TOOLS_ROUTES, NETWORK_TOOLS_CONNECTIONS})


register_permissions()
