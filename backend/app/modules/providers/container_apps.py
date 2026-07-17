from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerApp:
    id: str
    name: str
    description: str
    image: str
    container: str
    category: str
    panel_port: int
    ports: tuple[str, ...]
    version: str = "1"
    published_ports: tuple[tuple[int, int, str], ...] = ()
    volumes: tuple[tuple[str, str], ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    required_secrets: tuple[str, ...] = ()
    icon: str = "container"
    architectures: tuple[str, ...] = ("linux/amd64", "linux/arm64")
    healthcheck: str = "container_state"
    dependencies: tuple[str, ...] = ("docker",)
    minimum_memory_mb: int = 128
    documentation_url: str = ""
    update_strategy: str = "pull_recreate_with_rollback"
    backup_strategy: str = "webnas_container_and_named_volumes"
    uninstall_strategy: str = "remove_container_preserve_volumes"

    def container_definition(self, secret_environment: dict[str, str] | None = None) -> dict:
        supplied = secret_environment or {}
        missing = [key for key in self.required_secrets if not supplied.get(key)]
        if missing:
            from ...package_center.models import api_error

            api_error(422, "APP_SECRETS_REQUIRED", "Container application requires secret settings", fields=missing)
        published_target = next((target for published, target, _protocol in self.published_ports if published == self.panel_port), self.panel_port)
        healthcheck: dict[str, object] = {"type": "none"} if self.healthcheck in {"container_state", "dns_and_http"} else {"type": "http" if self.healthcheck == "http" else "tcp", "port": published_target, "path": "/"}
        return {
            "name": self.container,
            "image": self.image,
            "pull_policy": "always",
            "environment": dict(self.environment),
            "secret_environment": {},
            "ports": [{"published": published, "target": target, "protocol": protocol} for published, target, protocol in self.published_ports],
            "mounts": [{"type": "volume", "source": volume, "target": target} for volume, target in self.volumes],
            "network": "bridge",
            "restart_policy": "unless-stopped",
            "labels": {"io.webnas.app": self.id, "io.webnas.template-version": self.version},
            "healthcheck": healthcheck,
            "read_only": False,
            "init": True,
        }


# This is deliberately a closed catalog.  Entries are backed by provider code
# which builds fixed Docker argument arrays; values supplied by a browser never
# become image names, container names, mounts, or Docker flags.
CONTAINER_APPS = (
    ContainerApp(
        id="pihole",
        name="Pi-hole",
        description="Network-wide DNS filtering with a local administration panel.",
        image="pihole/pihole:latest",
        container="webnas-pihole",
        category="dns",
        panel_port=8080,
        ports=("53/tcp", "53/udp", "8080/tcp"),
        required_secrets=("WEBPASSWORD",), architectures=("linux/amd64", "linux/arm64", "linux/arm/v7"),
        healthcheck="dns_and_http", documentation_url="https://docs.pi-hole.net/docker/",
    ),
    ContainerApp(
        id="adguard-home",
        name="AdGuard Home",
        description="DNS filtering server with guided first-run configuration.",
        image="adguard/adguardhome:latest",
        container="webnas-adguard-home",
        category="dns",
        panel_port=3000,
        ports=("53/tcp", "53/udp", "3000/tcp", "8081/tcp", "8444/tcp", "8444/udp"),
        architectures=("linux/amd64", "linux/arm64", "linux/arm/v7"), healthcheck="http", documentation_url="https://github.com/AdguardTeam/AdGuardHome/wiki/Docker",
    ),
    ContainerApp(
        id="home-assistant",
        name="Home Assistant",
        description="Home automation server using the official stable container.",
        image="ghcr.io/home-assistant/home-assistant:stable",
        container="homeassistant",
        category="home_automation",
        panel_port=8123,
        ports=("8123/tcp",),
        architectures=("linux/amd64", "linux/arm64"), healthcheck="http", minimum_memory_mb=512, documentation_url="https://www.home-assistant.io/installation/linux#install-home-assistant-container",
    ),
    ContainerApp(
        id="uptime-kuma", name="Uptime Kuma", description="Self-hosted availability and response-time monitoring.",
        image="louislam/uptime-kuma:1", container="webnas-uptime-kuma", category="monitoring", panel_port=3001,
        ports=("3001/tcp",), published_ports=((3001, 3001, "tcp"),), volumes=(("webnas-uptime-kuma", "/app/data"),),
        healthcheck="http", documentation_url="https://github.com/louislam/uptime-kuma/wiki",
    ),
    ContainerApp(
        id="nginx-proxy-manager", name="Nginx Proxy Manager", description="Reverse proxy and TLS certificate management.",
        image="jc21/nginx-proxy-manager:latest", container="webnas-nginx-proxy-manager", category="network", panel_port=81,
        ports=("80/tcp", "81/tcp", "443/tcp"), published_ports=((80, 80, "tcp"), (81, 81, "tcp"), (443, 443, "tcp")),
        volumes=(("webnas-npm-data", "/data"), ("webnas-npm-letsencrypt", "/etc/letsencrypt")),
        healthcheck="http", minimum_memory_mb=256, documentation_url="https://nginxproxymanager.com/guide/",
    ),
    ContainerApp(
        id="jellyfin", name="Jellyfin", description="Media library and streaming server.",
        image="jellyfin/jellyfin:latest", container="webnas-jellyfin", category="media", panel_port=8096,
        ports=("8096/tcp",), published_ports=((8096, 8096, "tcp"),),
        volumes=(("webnas-jellyfin-config", "/config"), ("webnas-jellyfin-cache", "/cache")),
        healthcheck="http", minimum_memory_mb=512, documentation_url="https://jellyfin.org/docs/general/installation/container/",
    ),
    ContainerApp(
        id="syncthing", name="Syncthing", description="Continuous peer-to-peer file synchronization.",
        image="syncthing/syncthing:latest", container="webnas-syncthing", category="storage", panel_port=8384,
        ports=("8384/tcp", "22000/tcp", "22000/udp", "21027/udp"),
        published_ports=((8384, 8384, "tcp"), (22000, 22000, "tcp"), (22000, 22000, "udp"), (21027, 21027, "udp")),
        volumes=(("webnas-syncthing", "/var/syncthing"),),
        healthcheck="http", documentation_url="https://docs.syncthing.net/intro/getting-started.html",
    ),
    ContainerApp(
        id="nextcloud", name="Nextcloud", description="Private file sync, sharing and collaboration platform.",
        image="nextcloud:stable", container="webnas-nextcloud", category="storage", panel_port=8082,
        ports=("8082/tcp",), published_ports=((8082, 80, "tcp"),), volumes=(("webnas-nextcloud", "/var/www/html"),),
        healthcheck="http", minimum_memory_mb=512, documentation_url="https://github.com/nextcloud/docker",
    ),
    ContainerApp(
        id="mariadb-container", name="MariaDB", description="Relational database with persistent local storage.",
        image="mariadb:11", container="webnas-mariadb", category="database", panel_port=3306,
        ports=("3306/tcp",), published_ports=((3306, 3306, "tcp"),), volumes=(("webnas-mariadb", "/var/lib/mysql"),),
        required_secrets=("MARIADB_ROOT_PASSWORD",),
        healthcheck="tcp", minimum_memory_mb=256, documentation_url="https://hub.docker.com/_/mariadb",
    ),
    ContainerApp(
        id="postgresql-container", name="PostgreSQL", description="PostgreSQL database with persistent local storage.",
        image="postgres:17", container="webnas-postgresql", category="database", panel_port=5432,
        ports=("5432/tcp",), published_ports=((5432, 5432, "tcp"),), volumes=(("webnas-postgresql", "/var/lib/postgresql/data"),),
        environment=(("POSTGRES_USER", "postgres"),), required_secrets=("POSTGRES_PASSWORD",),
        healthcheck="tcp", minimum_memory_mb=256, documentation_url="https://hub.docker.com/_/postgres",
    ),
    ContainerApp(
        id="redis-container", name="Redis", description="In-memory data store for trusted local networks.",
        image="redis:7-alpine", container="webnas-redis", category="database", panel_port=6379,
        ports=("6379/tcp",), published_ports=((6379, 6379, "tcp"),), volumes=(("webnas-redis", "/data"),),
        healthcheck="tcp", documentation_url="https://hub.docker.com/_/redis",
    ),
)

CONTAINER_APPS_BY_ID = {item.id: item for item in CONTAINER_APPS}
