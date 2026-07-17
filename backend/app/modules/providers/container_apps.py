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
        ports=("53/tcp", "53/udp", "8080/tcp", "8443/tcp"),
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
    ),
)

CONTAINER_APPS_BY_ID = {item.id: item for item in CONTAINER_APPS}
