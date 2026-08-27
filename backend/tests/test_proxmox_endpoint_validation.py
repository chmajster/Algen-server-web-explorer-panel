from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.proxmox_manager.models import ProxmoxConnectionInput


def connection(endpoint: str) -> ProxmoxConnectionInput:
    return ProxmoxConnectionInput(
        name="Lab PVE",
        endpoint=endpoint,
        credential_id="proxmox-credential",
    )


def test_proxmox_connection_accepts_http_endpoint() -> None:
    payload = connection("http://pve.example:8006/")
    assert payload.endpoint == "http://pve.example:8006"


def test_proxmox_connection_accepts_https_endpoint() -> None:
    payload = connection("https://pve.example:8006/")
    assert payload.endpoint == "https://pve.example:8006"


def test_proxmox_connection_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValidationError, match="must use HTTP or HTTPS"):
        connection("ftp://pve.example:8006")
