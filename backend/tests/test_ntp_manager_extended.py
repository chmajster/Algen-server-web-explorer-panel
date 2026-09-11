from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.ntp_manager.diagnostics import parse_chrony_sources
from app.modules.ntp_manager.models import (
    NtpAllowedNetwork,
    NtpBackend,
    NtpConfiguration,
    NtpMode,
    NtpSourceInput,
    NtpSourceKind,
    NtpTimezoneInput,
)
from app.modules.ntp_manager.service import NtpService
from app.privileged_broker.infrastructure_policy import InfrastructurePolicyError, _ntp
from app.privileged_broker.protocol import BrokerRequest, Operation


def test_ntp_source_validation_accepts_hostname_ipv4_ipv6_and_rejects_injection():
    assert NtpSourceInput(server="time.cloudflare.com").server == "time.cloudflare.com"
    assert NtpSourceInput(server="192.0.2.10").server == "192.0.2.10"
    assert NtpSourceInput(server="2001:db8::10").server == "2001:db8::10"
    for value in ("pool.ntp.org;id", "$(id)", "../../etc/passwd", "host name", "0.0.0.0", "ff02::1"):
        with pytest.raises(ValidationError):
            NtpSourceInput(server=value)


def test_ntp_allowed_network_validation_supports_ipv4_and_ipv6():
    assert NtpAllowedNetwork(cidr="192.168.10.0/24").cidr == "192.168.10.0/24"
    assert NtpAllowedNetwork(cidr="2001:db8::/64").cidr == "2001:db8::/64"
    with pytest.raises(ValidationError):
        NtpAllowedNetwork(cidr="192.168.10.1/24")
    with pytest.raises(ValidationError):
        NtpAllowedNetwork(cidr="not-a-network")


def test_ntp_server_mode_requires_explicit_network_and_client_requires_source():
    with pytest.raises(ValidationError):
        NtpConfiguration(mode=NtpMode.server)
    with pytest.raises(ValidationError):
        NtpConfiguration(mode=NtpMode.client)
    configuration = NtpConfiguration(
        mode=NtpMode.client_server,
        sources=[NtpSourceInput(server="pool.ntp.org", kind=NtpSourceKind.pool)],
        allowed_networks=[NtpAllowedNetwork(cidr="10.0.0.0/8")],
    )
    assert configuration.mode == NtpMode.client_server


def test_ntp_render_generates_chrony_client_server_without_allow_all():
    service = NtpService()
    configuration = NtpConfiguration(
        mode=NtpMode.client_server,
        sources=[
            NtpSourceInput(server="time.cloudflare.com", prefer=True),
            NtpSourceInput(server="pool.ntp.org", kind=NtpSourceKind.pool),
        ],
        allowed_networks=[
            NtpAllowedNetwork(cidr="192.168.10.0/24", description="servers"),
            NtpAllowedNetwork(cidr="2001:db8::/64"),
        ],
        local_time_when_unsynced=True,
        local_stratum=10,
    )
    rendered = service._render(NtpBackend.chrony, "makestep 1.0 3\n", configuration)
    assert "server time.cloudflare.com iburst prefer" in rendered
    assert "pool pool.ntp.org iburst" in rendered
    assert "allow 192.168.10.0/24" in rendered
    assert "allow 2001:db8::/64" in rendered
    assert "local stratum 10" in rendered
    assert "allow all" not in rendered.lower()


def test_ntp_render_preserves_unmanaged_configuration():
    service = NtpService()
    original = "# distro managed\nserver distro.pool.example iburst\n"
    rendered = service._render(
        NtpBackend.chrony,
        original,
        NtpConfiguration(mode=NtpMode.client, sources=[NtpSourceInput(server="time.example.org")]),
    )
    assert "server distro.pool.example iburst" in rendered
    assert "# BEGIN WEBNAS NTP" in rendered
    assert "server time.example.org iburst" in rendered


def test_ntp_native_parser_maps_chrony_states():
    parsed = parse_chrony_sources(
        "^* 192.0.2.1 2 6 377 10 +1us[+2us] +/- 2ms\n"
        "^+ 192.0.2.2 2 6 377 12 +2us[+3us] +/- 2ms\n"
        "^- 192.0.2.3 2 6 377 12 +2us[+3us] +/- 2ms\n"
        "^? 192.0.2.4 0 6 0 - +0ns[+0ns] +/- 0ns\n"
        "^x 192.0.2.5 2 6 377 12 +2us[+3us] +/- 2ms\n"
        "^~ 192.0.2.6 2 6 377 12 +2us[+3us] +/- 2ms\n"
    )
    assert [item["state"] for item in parsed] == ["selected", "candidate", "outlier", "unreachable", "falseticker", "jittery"]


def test_ntp_timezone_input_rejects_path_traversal():
    assert NtpTimezoneInput(timezone="Europe/Warsaw").timezone == "Europe/Warsaw"
    assert NtpTimezoneInput(timezone="UTC").timezone == "UTC"
    for value in ("../UTC", "/etc/passwd", "Europe/../Warsaw", "Europe Warsaw"):
        with pytest.raises(ValidationError):
            NtpTimezoneInput(timezone=value)


def test_ntp_broker_rejects_unallowlisted_service_and_target():
    request = BrokerRequest(
        request_id="a" * 32,
        actor="pytest",
        operation=Operation.NTP,
        payload={"action": "service", "service_action": "restart", "unit": "sshd"},
    )
    with pytest.raises(InfrastructurePolicyError):
        _ntp(request)

    request = BrokerRequest(
        request_id="b" * 32,
        actor="pytest",
        operation=Operation.NTP,
        payload={"action": "write_config", "target": "arbitrary", "content": "server x"},
    )
    with pytest.raises(InfrastructurePolicyError):
        _ntp(request)


def test_ntp_backup_metadata_is_local_and_actor_scoped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = NtpService()
    service.backups_root = tmp_path
    target = Path("/etc/chrony/chrony.conf")
    metadata = service._backup(target, "server old.example\n", actor="alice", change="config_apply", existed=True)
    assert metadata["actor"] == "alice"
    assert metadata["change"] == "config_apply"
    assert (tmp_path / f"{metadata['id']}.conf").read_text(encoding="utf-8") == "server old.example\n"
    listed = service.list_backups()
    assert listed[0]["id"] == metadata["id"]
