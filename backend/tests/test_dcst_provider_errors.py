from app.modules.dcst.provider import ProxmoxFirewallProvider, ProviderContext


class FailingClient:
    def get(self, _path: str):
        raise RuntimeError("secret token=abc123 host=https://private-pve.example")


def test_provider_status_does_not_expose_upstream_exception(monkeypatch):
    provider = ProxmoxFirewallProvider()
    context = ProviderContext({"id": "pve-1", "name": "PVE"}, FailingClient())  # type: ignore[arg-type]
    monkeypatch.setattr(provider, "contexts", lambda: [context])

    result = provider.status()

    assert result["connections"][0]["error"] == "Proxmox API request failed"
    assert "abc123" not in str(result)
    assert "private-pve" not in str(result)


def test_provider_connection_test_does_not_expose_upstream_exception(monkeypatch):
    provider = ProxmoxFirewallProvider()
    context = ProviderContext({"id": "pve-1", "name": "PVE"}, FailingClient())  # type: ignore[arg-type]
    monkeypatch.setattr(provider, "contexts", lambda: [context])

    result = provider.test()

    assert result["connections"][0]["error"] == "Proxmox API request failed"
    assert "abc123" not in str(result)
    assert "private-pve" not in str(result)
