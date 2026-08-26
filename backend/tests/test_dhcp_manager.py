from __future__ import annotations

import importlib
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.identity.models import Role
from app.identity.permissions import Permission, ROLE_PERMISSIONS
from app.modules.dhcp.models import DhcpBackend, DhcpConfiguration, DhcpLease, DhcpReservation, DhcpSubnet, normalize_mac
from app.modules.dhcp.service import DhcpService
from app.modules.dhcp.system import BackendDefinition, DhcpSystem
from app.package_center.models import PackageAction
from app.security import SessionUser


def subnet(**changes) -> DhcpSubnet:
    values = {
        "id": "lan",
        "name": "LAN",
        "cidr": "10.0.10.0/24",
        "gateway": "10.0.10.1",
        "pool_start": "10.0.10.100",
        "pool_end": "10.0.10.200",
        "dns_servers": ["10.0.10.2"],
        "domain_name": "lab.local",
        "lease_time": 3600,
        "max_lease_time": 7200,
    }
    values.update(changes)
    return DhcpSubnet(**values)


def reservation(**changes) -> DhcpReservation:
    values = {
        "id": "host1",
        "hostname": "host1.lab.local",
        "mac_address": "02:00:00:00:00:01",
        "ipv4_address": "10.0.10.20",
        "subnet_id": "lan",
    }
    values.update(changes)
    return DhcpReservation(**values)


class FakeSystem(DhcpSystem):
    def __init__(self, root: Path) -> None:
        definition = BackendDefinition(
            backend=DhcpBackend.kea,
            executable="kea-dhcp4",
            services=("kea-dhcp4-server",),
            config_path=root / "etc" / "kea" / "kea-dhcp4.conf",
            leases_path=root / "var" / "kea-leases4.csv",
        )
        super().__init__(definitions={DhcpBackend.kea: definition})
        self.actions: list[str] = []
        self.definition = definition

    def detect_backend(self) -> DhcpBackend:
        return DhcpBackend.kea

    def selected_service(self, backend: DhcpBackend) -> str:
        return "kea-dhcp4-server"

    def service_state(self, service: str) -> tuple[str, bool]:
        return "active", True

    def service_action(self, backend: DhcpBackend, action: str) -> subprocess.CompletedProcess[str]:
        self.actions.append(action)
        return subprocess.CompletedProcess(["systemctl", action, "kea-dhcp4-server"], 0, "", "")

    def validate_candidate(self, backend: DhcpBackend, path: Path) -> tuple[bool, str]:
        return True, "valid"

    def interfaces(self, enabled: set[str] | None = None):
        return []

    def parse_leases(self, backend: DhcpBackend):
        return []

    def version(self, backend: DhcpBackend) -> str:
        return "2.6.1"

    def logs(self, backend: DhcpBackend, *, limit: int = 200, search: str = "", level: str = "", since: str = ""):
        return {"source": "journal:kea-dhcp4-server", "sources": [], "lines": [], "truncated": False}


def dhcp_service(tmp_path: Path, monkeypatch) -> tuple[DhcpService, FakeSystem]:
    service_module = importlib.import_module("app.modules.dhcp.service")
    monkeypatch.setattr(service_module, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"))))
    system = FakeSystem(tmp_path)
    service = DhcpService(tmp_path / "data" / "dhcp", system=system)
    return service, system


def test_subnet_validation_rejects_invalid_pool_and_network_boundaries():
    with pytest.raises(ValidationError, match="pool start"):
        subnet(pool_start="10.0.10.200", pool_end="10.0.10.100")
    with pytest.raises(ValidationError, match="inside its subnet"):
        subnet(pool_start="10.0.11.10")
    with pytest.raises(ValidationError, match="network or broadcast"):
        subnet(pool_start="10.0.10.0")
    with pytest.raises(ValidationError, match="network or broadcast"):
        subnet(pool_end="10.0.10.255")
    with pytest.raises(ValidationError):
        subnet(cidr="10.0.10.1/24")


def test_mac_ip_and_reservation_validation():
    assert normalize_mac("02-00-00-00-00-01") == "02:00:00:00:00:01"
    with pytest.raises(ValueError, match="MAC"):
        normalize_mac("zz:00:00:00:00:01")
    with pytest.raises(ValueError, match="multicast"):
        normalize_mac("01:00:00:00:00:01")
    with pytest.raises(ValidationError):
        reservation(ipv4_address="2001:db8::1")


def test_configuration_detects_overlaps_duplicates_pool_and_active_lease_conflicts(tmp_path: Path, monkeypatch):
    service, _ = dhcp_service(tmp_path, monkeypatch)
    config = DhcpConfiguration(
        subnets=[subnet(), subnet(id="lan2", name="LAN 2", cidr="10.0.10.0/25", gateway="10.0.10.1", pool_start="10.0.10.50", pool_end="10.0.10.90")],
        reservations=[
            reservation(),
            reservation(id="host2", hostname="host2.lab.local", mac_address="02:00:00:00:00:01", ipv4_address="10.0.10.20"),
            reservation(id="dynamic", hostname="dynamic.lab.local", mac_address="02:00:00:00:00:03", ipv4_address="10.0.10.110"),
        ],
    )
    monkeypatch.setattr(service, "_leases_with_metadata", lambda _config=None: [DhcpLease(id="lease1", ipv4_address="10.0.10.20", mac_address="02:00:00:00:00:99", state="active")])
    result = service.validate_configuration(config, native=False)
    codes = {item.code for item in result.issues}
    assert {"OVERLAPPING_SUBNETS", "DUPLICATE_MAC", "DUPLICATE_IP", "RESERVATION_IN_DYNAMIC_POOL", "ACTIVE_LEASE_CONFLICT"} <= codes
    assert result.ok is False


def test_kea_and_isc_render_parse_round_trip():
    config = DhcpConfiguration(
        interfaces=["eth0"],
        subnets=[subnet(tftp_server="10.0.10.5", boot_filename="pxelinux.0", pxe_enabled=True)],
        reservations=[reservation(client_identifier="client-1")],
    )
    kea = DhcpSystem.render_kea(config)
    assert '"subnet": "10.0.10.0/24"' in kea
    parsed_kea = DhcpSystem.parse_kea(kea)
    assert parsed_kea.interfaces == ["eth0"]
    assert parsed_kea.subnets[0].pool_start == "10.0.10.100"
    assert parsed_kea.reservations[0].mac_address == "02:00:00:00:00:01"

    isc = DhcpSystem.render_isc(config)
    assert "range 10.0.10.100 10.0.10.200;" in isc
    assert "hardware ethernet 02:00:00:00:00:01;" in isc
    parsed_isc = DhcpSystem.parse_isc(isc)
    assert parsed_isc.subnets[0].cidr == "10.0.10.0/24"
    assert parsed_isc.reservations[0].ipv4_address == "10.0.10.20"


def test_native_validation_uses_fixed_argument_arrays(monkeypatch, tmp_path: Path):
    system = FakeSystem(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(system, "_which", lambda name: f"/usr/sbin/{name}")

    def run(args: list[str], **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(system, "_run", run)
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    ok, _ = system.validate_candidate(DhcpBackend.kea, candidate)
    assert ok is True
    assert calls == [["/usr/sbin/kea-dhcp4", "-t", str(candidate)]]


def test_service_control_allowlist_never_accepts_browser_unit(monkeypatch, tmp_path: Path):
    system = FakeSystem(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(system, "_which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(system, "selected_service", lambda _backend: "kea-dhcp4-server")
    monkeypatch.setattr(system, "_run", lambda args, **_kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
    system.service_action(DhcpBackend.kea, "restart")
    assert calls == [["/usr/bin/systemctl", "restart", "kea-dhcp4-server"]]
    with pytest.raises(ValueError, match="unsupported"):
        system.service_action(DhcpBackend.kea, "restart;rm -rf /")


def test_backup_is_private_and_checksum_is_verified(tmp_path: Path, monkeypatch):
    service, system = dhcp_service(tmp_path, monkeypatch)
    system.definition.config_path.parent.mkdir(parents=True)
    system.definition.config_path.write_text(DhcpSystem.render_kea(DhcpConfiguration(subnets=[subnet()])), encoding="utf-8")
    service._write_state(DhcpConfiguration(subnets=[subnet()]), DhcpBackend.kea, "admin")
    backup = service.create_backup("admin", "manual")
    directory = service.backups_root / backup["id"]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir() if path.is_file())
    service._verified_backup(backup["id"])
    (directory / "webnas-state.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        service._verified_backup(backup["id"])


def test_apply_failure_restores_previous_configuration_and_verifies_rollback(tmp_path: Path, monkeypatch):
    service, system = dhcp_service(tmp_path, monkeypatch)
    system.definition.config_path.parent.mkdir(parents=True)
    previous = DhcpConfiguration(subnets=[subnet()])
    system.definition.config_path.write_text(DhcpSystem.render_kea(previous), encoding="utf-8")
    service._write_state(previous, DhcpBackend.kea, "admin")
    original = system.definition.config_path.read_bytes()
    monkeypatch.setattr(service, "create_backup", lambda *_args, **_kwargs: {"id": "backup"})
    monkeypatch.setattr(service, "_restart_and_verify", lambda _backend: (_ for _ in ()).throw(RuntimeError("new config failed")))
    verified: list[DhcpBackend] = []
    monkeypatch.setattr(service, "_restart_previous_and_verify", lambda backend: verified.append(backend))
    proposed = DhcpConfiguration(subnets=[subnet(pool_start="10.0.10.120")])
    with pytest.raises(RuntimeError, match="new config failed"):
        service.apply_configuration(proposed, "admin")
    assert system.definition.config_path.read_bytes() == original
    assert verified == [DhcpBackend.kea]
    assert service.configuration().subnets[0].pool_start == "10.0.10.100"


def test_restore_failure_rolls_back_and_verifies_previous_service(tmp_path: Path, monkeypatch):
    service, system = dhcp_service(tmp_path, monkeypatch)
    system.definition.config_path.parent.mkdir(parents=True)
    previous = DhcpConfiguration(subnets=[subnet()])
    system.definition.config_path.write_text(DhcpSystem.render_kea(previous), encoding="utf-8")
    service._write_state(previous, DhcpBackend.kea, "admin")
    backup = service.create_backup("admin", "restore-source")
    system.definition.config_path.write_text("previous-live-config", encoding="utf-8")
    before = system.definition.config_path.read_bytes()
    monkeypatch.setattr(service, "create_backup", lambda *_args, **_kwargs: {"id": "safety"})
    monkeypatch.setattr(service, "_restart_and_verify", lambda _backend: (_ for _ in ()).throw(RuntimeError("restored service failed")))
    verified: list[DhcpBackend] = []
    monkeypatch.setattr(service, "_restart_previous_and_verify", lambda backend: verified.append(backend))
    with pytest.raises(RuntimeError, match="restored service failed"):
        service.restore_backup(backup["id"], "admin")
    assert system.definition.config_path.read_bytes() == before
    assert verified == [DhcpBackend.kea]


def test_rbac_defaults_are_granular_and_auditor_is_read_only():
    dhcp_permissions = {permission.value for permission in Permission if permission.value.startswith("dhcp.")}
    assert dhcp_permissions <= ROLE_PERMISSIONS[Role.admin]
    assert {Permission.DHCP_VIEW.value, Permission.DHCP_LEASES_VIEW.value, Permission.DHCP_DIAGNOSTICS.value} <= ROLE_PERMISSIONS[Role.auditor]
    assert Permission.DHCP_CONFIGURE.value not in ROLE_PERMISSIONS[Role.auditor]
    assert Permission.DHCP_RESTORE.value not in ROLE_PERMISSIONS[Role.operator]
    assert Permission.DHCP_INSTALL.value not in ROLE_PERMISSIONS[Role.operator]


def test_package_center_requires_dhcp_specific_install_and_uninstall_permissions(monkeypatch):
    package_router = importlib.import_module("app.package_center.router")
    requested: list[Permission | str] = []
    monkeypatch.setattr(package_router, "authorize", lambda _user, permission: requested.append(permission))
    user = SessionUser(username="admin", csrf_token="csrf")
    package_router._authorize_module_package_action("dhcp", PackageAction.install, user)
    package_router._authorize_module_package_action("dhcp", PackageAction.uninstall, user)
    assert Permission.DHCP_INSTALL in requested
    assert Permission.DHCP_UNINSTALL in requested


def test_pam_confirmation_and_proxmox_safe_mode_are_backend_enforced(monkeypatch):
    dhcp_router = importlib.import_module("app.modules.dhcp.router")
    user = SessionUser(username="admin", csrf_token="csrf")
    authenticated: list[tuple[str, str]] = []
    monkeypatch.setattr(dhcp_router, "authenticate", lambda username, password: authenticated.append((username, password)) or True)
    dhcp_router._critical(user, "secret", "expected", "expected")
    assert authenticated == [("admin", "secret")]
    with pytest.raises(HTTPException) as confirmation_error:
        dhcp_router._critical(user, "secret", "wrong", "expected")
    assert confirmation_error.value.status_code == 400

    monkeypatch.setattr(dhcp_router, "_ready", lambda: None)
    monkeypatch.setattr(dhcp_router, "get_module", lambda _module_id: {"blocked_by_proxmox": True})
    with pytest.raises(HTTPException) as safe_mode_error:
        dhcp_router._mutation_ready()
    assert safe_mode_error.value.status_code == 403


def test_mutating_routes_use_central_csrf_dependency():
    dhcp_router = importlib.import_module("app.modules.dhcp.router")
    mutation_methods = {"POST", "PUT", "DELETE", "PATCH"}
    mutating = [route for route in dhcp_router.router.routes if getattr(route, "methods", set()) & mutation_methods]
    assert mutating
    for route in mutating:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        assert dhcp_router.mutating_user in dependencies
