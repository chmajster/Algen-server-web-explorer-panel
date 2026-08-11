"""Built-in WebNAS module catalog.

The order is also the default presentation order used by Package Center.  Keep
Samba in this registry instead of exposing it only as a legacy desktop app.
"""

BUILTIN_MODULE_IDS = (
    "samba",
    "linux-updates",
    "docker",
    "ansible-controller",
    "apmid",
    "os-repositories",
    "cron",
    "pihole",
    "adguard-home",
    "postgresql",
    "mariadb",
    "redis",
    "home-assistant",
    "nginx",
    "squid",
    "syncthing",
)

__all__ = ["BUILTIN_MODULE_IDS"]
