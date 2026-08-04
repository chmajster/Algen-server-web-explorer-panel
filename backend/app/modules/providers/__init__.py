from __future__ import annotations

from .base import ModuleProvider
from .ansible_controller import AnsibleControllerProvider
from .apmid import ApmidProvider
from .databases import MariaDBProvider, PostgreSQLProvider, RedisProvider
from .dns import AdGuardHomeProvider, PiHoleProvider
from .docker import DockerProvider
from .infrastructure import ApiConnectionProvider
from .home_assistant import HomeAssistantProvider
from .linux_updates import LinuxUpdatesProvider
from .os_repositories import OsRepositoriesProvider
from .samba import SambaProvider, parse_smb_conf


def get_provider(module_id: str, actor: str = "root") -> ModuleProvider:
    providers = {
        "samba": SambaProvider,
        "linux-updates": LinuxUpdatesProvider,
        "docker": DockerProvider,
        "pihole": PiHoleProvider,
        "adguard-home": AdGuardHomeProvider,
        "postgresql": PostgreSQLProvider,
        "mariadb": MariaDBProvider,
        "redis": RedisProvider,
        "home-assistant": HomeAssistantProvider,
        "ansible-controller": AnsibleControllerProvider,
        "apmid": ApmidProvider,
        "os-repositories": OsRepositoriesProvider,
    }
    provider = providers.get(module_id)
    if provider:
        if provider in {SambaProvider, AnsibleControllerProvider}:
            return provider(actor)
        return provider(module_id)
    return ModuleProvider(module_id)


__all__ = ["AdGuardHomeProvider", "AnsibleControllerProvider", "ApiConnectionProvider", "ApmidProvider", "DockerProvider", "HomeAssistantProvider", "LinuxUpdatesProvider", "MariaDBProvider", "ModuleProvider", "OsRepositoriesProvider", "PiHoleProvider", "PostgreSQLProvider", "RedisProvider", "SambaProvider", "get_provider", "parse_smb_conf"]
