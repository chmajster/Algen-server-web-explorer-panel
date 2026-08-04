from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.docker_manager.models import ContainerCreateRequest


def test_container_create_accepts_host_network() -> None:
    request = ContainerCreateRequest.model_validate(
        {
            "name": "host-network-test",
            "image": "nginx:stable",
            "network": "host",
        }
    )

    assert request.network == "host"
    assert request.ports == []
    assert request.network_aliases == []


def test_container_create_trims_host_network_name() -> None:
    request = ContainerCreateRequest.model_validate(
        {
            "name": "host-network-test",
            "image": "nginx:stable",
            "network": "host ",
        }
    )

    assert request.network == "host"


def test_host_network_rejects_published_ports() -> None:
    with pytest.raises(ValidationError, match="does not accept published ports"):
        ContainerCreateRequest.model_validate(
            {
                "name": "host-network-test",
                "image": "nginx:stable",
                "network": "host",
                "ports": [
                    {
                        "published": 8080,
                        "target": 80,
                        "protocol": "tcp",
                    }
                ],
            }
        )


def test_host_network_rejects_network_aliases() -> None:
    with pytest.raises(ValidationError, match="does not accept network aliases"):
        ContainerCreateRequest.model_validate(
            {
                "name": "host-network-test",
                "image": "nginx:stable",
                "network": "host",
                "network_aliases": ["web"],
            }
        )


def test_none_network_remains_forbidden() -> None:
    with pytest.raises(ValidationError, match="none network mode is forbidden"):
        ContainerCreateRequest.model_validate(
            {
                "name": "none-network-test",
                "image": "nginx:stable",
                "network": "none",
            }
        )
