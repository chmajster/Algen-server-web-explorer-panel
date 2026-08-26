from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from ...config import get_config
from ...package_center.executor import redact
from ..hosts_manager.public import ConnectionType, HostInput, find_host, registry as hosts_registry
from ..providers.public import upsert_dns_record
from .models import (
    DhcpBackend,
    DhcpConfiguration,
    DhcpConfigurationPlan,
    DhcpDiagnostic,
    DhcpInterface,
    DhcpLease,
    DhcpReservation,
    DhcpStatus,
    DhcpSubnet,
    DhcpUtilization,
    DhcpValidationIssue,
    DhcpValidationResult,
)
from .system import DhcpSystem


class DhcpNotFoundError(KeyError):
    pass


class DhcpConflictError(ValueError):
    pass


class DhcpService:
    def __init__(self, root: Path | None = None, *, system: DhcpSystem | None = None) -> None:
        data_dir = Path(get_config().paths.data_dir)
        self.root = root or data_dir / "dhcp"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.inputs_root = self.root / "inputs"
        self.inputs_root.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.inputs_root, 0o700)
        self.state_path = self.root / "state.json"
        self.backups_root = data_dir / "module-backups" / "dhcp"
        self.backups_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.backups_root, 0o700)
        self.system = system or DhcpSystem()
        self._lock = threading.RLock()

    @staticmethod
    def _atomic_write(path: Path, content: bytes, *, default_mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = (path.stat().st_mode & 0o777) if path.exists() else default_mode
        temporary = path.with_name(f".{path.name}.webnas-{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            temporary.unlink(missing_ok=True)

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, config: DhcpConfiguration, backend: DhcpBackend, actor: str) -> None:
        payload = {
            "schema_version": 1,
            "backend": backend.value,
            "configuration": config.model_dump(mode="json"),
            "updated_at": time.time(),
            "updated_by": actor,
        }
        self._atomic_write(self.state_path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(), default_mode=0o600)
        os.chmod(self.state_path, 0o600)

    def stage_input(self, payload: dict[str, Any]) -> str:
        reference = uuid4().hex
        target = self.inputs_root / f"{reference}.json"
        self._atomic_write(target, (json.dumps(payload, ensure_ascii=False) + "\n").encode(), default_mode=0o600)
        os.chmod(target, 0o600)
        return reference

    def read_input(self, reference: str) -> dict[str, Any]:
        if not reference or not all(character in "0123456789abcdef" for character in reference) or len(reference) != 32:
            raise ValueError("invalid staged DHCP input reference")
        path = self.inputs_root / f"{reference}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid staged DHCP payload")
        return payload

    def discard_input(self, reference: str) -> None:
        if reference and len(reference) == 32 and all(character in "0123456789abcdef" for character in reference):
            (self.inputs_root / f"{reference}.json").unlink(missing_ok=True)

    def backend(self) -> DhcpBackend:
        return self.system.detect_backend()

    def configuration(self) -> DhcpConfiguration:
        state = self._read_state()
        if isinstance(state.get("configuration"), dict):
            try:
                return DhcpConfiguration.model_validate(state["configuration"])
            except ValueError:
                pass
        backend = self.backend()
        definition = self.system.definitions.get(backend)
        if definition and definition.config_path.is_file():
            try:
                config = self.system.parse_config(backend, definition.config_path.read_text(encoding="utf-8", errors="replace"))
                if backend == DhcpBackend.isc and definition.interface_config_path and definition.interface_config_path.is_file():
                    match = __import__("re").search(r'^INTERFACESv4="([^"]*)"', definition.interface_config_path.read_text(encoding="utf-8", errors="replace"), __import__("re").M)
                    if match:
                        config.interfaces = [item for item in match.group(1).split() if item]
                return config
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return DhcpConfiguration()

    def _leases_with_metadata(self, config: DhcpConfiguration | None = None) -> list[DhcpLease]:
        config = config or self.configuration()
        subnet_by_native: dict[str, DhcpSubnet] = {}
        for index, subnet in enumerate((item for item in config.subnets if item.enabled), start=1):
            subnet_by_native[str(index)] = subnet
        reservations_by_ip = {item.ipv4_address: item for item in config.reservations if item.enabled}
        values: list[DhcpLease] = []
        for lease in self.system.leases(self.backend()):
            matched_subnet = subnet_by_native.get(lease.subnet_id)
            if matched_subnet is None:
                try:
                    address = ipaddress.ip_address(lease.ipv4_address)
                    matched_subnet = next((item for item in config.subnets if address in ipaddress.IPv4Network(item.cidr, strict=True)), None)
                except ValueError:
                    matched_subnet = None
            values.append(lease.model_copy(update={
                "subnet_id": matched_subnet.id if matched_subnet else lease.subnet_id,
                "subnet": matched_subnet.cidr if matched_subnet else "",
                "reserved": lease.ipv4_address in reservations_by_ip,
            }))
        return values

    def leases(self, *, search: str = "", subnet_id: str = "", state: str = "", sort: str = "ipv4_address") -> list[DhcpLease]:
        values = self._leases_with_metadata()
        needle = search.casefold().strip()
        if needle:
            values = [item for item in values if needle in " ".join((item.hostname, item.ipv4_address, item.mac_address, item.client_identifier)).casefold()]
        if subnet_id:
            values = [item for item in values if item.subnet_id == subnet_id]
        if state == "reserved":
            values = [item for item in values if item.reserved]
        elif state in {"active", "expired", "declined", "released", "unknown"}:
            values = [item for item in values if item.state == state]
        keys = {
            "ipv4_address": lambda item: int(ipaddress.ip_address(item.ipv4_address)),
            "hostname": lambda item: item.hostname.casefold(),
            "lease_end": lambda item: item.lease_end or 0,
            "remaining": lambda item: item.remaining_seconds,
            "state": lambda item: item.state,
        }
        return sorted(values, key=keys.get(sort, keys["ipv4_address"]))

    @staticmethod
    def _pool_bounds(subnet: DhcpSubnet) -> tuple[int, int]:
        return int(ipaddress.ip_address(subnet.pool_start)), int(ipaddress.ip_address(subnet.pool_end))

    def validate_configuration(self, config: DhcpConfiguration, *, native: bool = True) -> DhcpValidationResult:
        issues: list[DhcpValidationIssue] = []
        subnet_ids: set[str] = set()
        networks: list[tuple[DhcpSubnet, ipaddress.IPv4Network]] = []
        for subnet in config.subnets:
            if subnet.id in subnet_ids:
                issues.append(DhcpValidationIssue(level="error", code="DUPLICATE_SUBNET_ID", message="Duplicate subnet identifier", object_id=subnet.id))
            subnet_ids.add(subnet.id)
            network = ipaddress.IPv4Network(subnet.cidr, strict=True)
            for previous, previous_network in networks:
                if network.overlaps(previous_network):
                    issues.append(DhcpValidationIssue(level="error", code="OVERLAPPING_SUBNETS", message=f"Subnet {subnet.cidr} overlaps {previous.cidr}", object_id=subnet.id))
            networks.append((subnet, network))
        available_interfaces = {item.name for item in self.system.interfaces(set(config.interfaces))}
        for interface in config.interfaces:
            if interface not in available_interfaces:
                issues.append(DhcpValidationIssue(level="error", code="INTERFACE_NOT_FOUND", message=f"Network interface {interface} does not exist", object_id=interface))
        macs: dict[str, str] = {}
        addresses: dict[str, str] = {}
        active_leases = {item.ipv4_address: item for item in self._leases_with_metadata(config) if item.state == "active"}
        subnet_map = {item.id: item for item in config.subnets}
        for reservation in config.reservations:
            if reservation.mac_address in macs:
                issues.append(DhcpValidationIssue(level="error", code="DUPLICATE_MAC", message=f"MAC {reservation.mac_address} is already reserved", object_id=reservation.id))
            else:
                macs[reservation.mac_address] = reservation.id
            if reservation.ipv4_address in addresses:
                issues.append(DhcpValidationIssue(level="error", code="DUPLICATE_IP", message=f"IP {reservation.ipv4_address} is already reserved", object_id=reservation.id))
            else:
                addresses[reservation.ipv4_address] = reservation.id
            reservation_subnet = subnet_map.get(reservation.subnet_id)
            if not reservation_subnet:
                issues.append(DhcpValidationIssue(level="error", code="RESERVATION_SUBNET_NOT_FOUND", message="Reservation references an unknown subnet", object_id=reservation.id))
                continue
            address = ipaddress.ip_address(reservation.ipv4_address)
            network = ipaddress.IPv4Network(reservation_subnet.cidr, strict=True)
            if address not in network or address in {network.network_address, network.broadcast_address}:
                issues.append(DhcpValidationIssue(level="error", code="RESERVATION_OUTSIDE_SUBNET", message=f"Reservation {reservation.ipv4_address} is outside {reservation_subnet.cidr}", object_id=reservation.id))
            start, end = self._pool_bounds(reservation_subnet)
            if start <= int(address) <= end:
                issues.append(DhcpValidationIssue(level="error", code="RESERVATION_IN_DYNAMIC_POOL", message=f"Reservation {reservation.ipv4_address} is inside the dynamic pool", object_id=reservation.id))
            lease = active_leases.get(reservation.ipv4_address)
            if lease and lease.mac_address and lease.mac_address.lower() != reservation.mac_address.lower():
                issues.append(DhcpValidationIssue(level="error", code="ACTIVE_LEASE_CONFLICT", message=f"Address {reservation.ipv4_address} is leased to another client", object_id=reservation.id))
        for subnet in config.subnets:
            start, end = self._pool_bounds(subnet)
            for other in config.subnets:
                if other.id <= subnet.id:
                    continue
                other_start, other_end = self._pool_bounds(other)
                if max(start, other_start) <= min(end, other_end):
                    issues.append(DhcpValidationIssue(level="error", code="OVERLAPPING_POOLS", message=f"Pool for {subnet.name} overlaps pool for {other.name}", object_id=subnet.id))
        backend = self.backend()
        candidate_hash, native_output = "", ""
        if not any(item.level == "error" for item in issues):
            try:
                rendered = self.system.render(backend, config) if backend != DhcpBackend.none else ""
                candidate_hash = hashlib.sha256(rendered.encode()).hexdigest() if rendered else ""
                if native and backend != DhcpBackend.none:
                    suffix = ".json" if backend == DhcpBackend.kea else ".conf"
                    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, dir=self.root, delete=False) as handle:
                        handle.write(rendered)
                        candidate = Path(handle.name)
                    try:
                        ok, native_output = self.system.validate_candidate(backend, candidate)
                        if not ok:
                            issues.append(DhcpValidationIssue(level="error", code="NATIVE_VALIDATION_FAILED", message=native_output or "Native DHCP validation failed"))
                    finally:
                        candidate.unlink(missing_ok=True)
            except (OSError, RuntimeError, ValueError) as error:
                issues.append(DhcpValidationIssue(level="error", code="RENDER_FAILED", message=str(error)))
        if backend == DhcpBackend.none:
            issues.append(DhcpValidationIssue(level="warning", code="BACKEND_NOT_INSTALLED", message="Install Kea DHCP4 from Module Center before applying configuration"))
        return DhcpValidationResult(ok=not any(item.level == "error" for item in issues), backend=backend, issues=issues, native_output=native_output, candidate_sha256=candidate_hash)

    def plan(self, proposed: DhcpConfiguration) -> DhcpConfigurationPlan:
        current = self.configuration()
        validation = self.validate_configuration(proposed)
        old_subnets, new_subnets = {item.id: item for item in current.subnets}, {item.id: item for item in proposed.subnets}
        old_reservations, new_reservations = {item.id: item for item in current.reservations}, {item.id: item for item in proposed.reservations}
        globals_changed = [key for key in ("interfaces", "authoritative", "default_lease_time", "max_lease_time", "thresholds") if current.model_dump(mode="json")[key] != proposed.model_dump(mode="json")[key]]
        return DhcpConfigurationPlan(
            validation=validation,
            added_subnets=sorted(set(new_subnets) - set(old_subnets)), removed_subnets=sorted(set(old_subnets) - set(new_subnets)),
            changed_subnets=sorted(key for key in set(old_subnets) & set(new_subnets) if old_subnets[key] != new_subnets[key]),
            added_reservations=sorted(set(new_reservations) - set(old_reservations)), removed_reservations=sorted(set(old_reservations) - set(new_reservations)),
            changed_reservations=sorted(key for key in set(old_reservations) & set(new_reservations) if old_reservations[key] != new_reservations[key]),
            changed_global_options=globals_changed,
            warnings=[item.message for item in validation.issues if item.level == "warning"],
        )

    def utilization(self, config: DhcpConfiguration | None = None) -> list[DhcpUtilization]:
        config = config or self.configuration()
        active = {item.ipv4_address for item in self._leases_with_metadata(config) if item.state == "active"}
        result: list[DhcpUtilization] = []
        for subnet in config.subnets:
            start, end = self._pool_bounds(subnet)
            total = end - start + 1
            used = sum(1 for address in active if start <= int(ipaddress.ip_address(address)) <= end)
            available = max(0, total - used)
            usage = round((used / total * 100) if total else 0, 1)
            thresholds = config.thresholds
            level: Literal["normal", "warning", "critical", "emergency"] = "emergency" if usage >= thresholds.emergency else "critical" if usage >= thresholds.critical else "warning" if usage >= thresholds.warning else "normal"
            result.append(DhcpUtilization(subnet_id=subnet.id, subnet=subnet.cidr, pool_start=subnet.pool_start, pool_end=subnet.pool_end, used=used, available=available, total=total, usage_percent=usage, level=level))
        return result

    def status(self, *, installed: bool, blocked_by_proxmox: bool = False) -> DhcpStatus:
        backend = self.backend()
        config = self.configuration()
        leases = self._leases_with_metadata(config)
        utilization = self.utilization(config)
        service = self.system.selected_service(backend)
        state, enabled = self.system.service_state(service) if service else ("not_installed", False)
        validation = self.validate_configuration(config, native=backend != DhcpBackend.none) if installed else None
        active = sum(1 for item in leases if item.state == "active")
        health: Literal["healthy", "degraded", "failed", "unknown", "not_installed"] = "not_installed" if not installed or backend == DhcpBackend.none else "failed" if state == "failed" else "healthy" if state == "active" and validation and validation.ok else "degraded" if state in {"active", "inactive", "failed"} else "unknown"
        recent_errors = [line for line in self.system.logs(backend, limit=80).get("lines", []) if any(word in line.casefold() for word in ("error", "failed", "fatal"))][-5:] if backend != DhcpBackend.none else []
        state_data = self._read_state()
        updated_at = state_data.get("updated_at")
        last_config_change = float(updated_at) if isinstance(updated_at, (int, float)) else None
        return DhcpStatus(
            installed=installed, backend=backend, version=self.system.version(backend), service=service, service_state=state,
            service_enabled=enabled, uptime_seconds=self.system.service_uptime(backend), interfaces=config.interfaces,
            active_leases=active, available_addresses=sum(item.available for item in utilization), used_addresses=sum(item.used for item in utilization),
            subnet_count=len(config.subnets), reservation_count=len(config.reservations), last_errors=recent_errors,
            last_config_change=last_config_change,
            configuration_valid=validation.ok if validation else None, health=health, blocked_by_proxmox=blocked_by_proxmox,
        )

    def interfaces(self) -> list[DhcpInterface]:
        return self.system.interfaces(set(self.configuration().interfaces))

    def _target_contents(self, backend: DhcpBackend, config: DhcpConfiguration) -> dict[Path, bytes]:
        definition = self.system.definitions.get(backend)
        if not definition:
            raise RuntimeError("No supported DHCP backend is installed")
        values = {definition.config_path: self.system.render(backend, config).encode()}
        if backend == DhcpBackend.isc and definition.interface_config_path:
            values[definition.interface_config_path] = self.system.render_isc_interfaces(config).encode()
        return values

    @staticmethod
    def _snapshot(paths: list[Path]) -> dict[Path, tuple[bytes | None, int]]:
        snapshot: dict[Path, tuple[bytes | None, int]] = {}
        for path in paths:
            if path.exists():
                snapshot[path] = (path.read_bytes(), path.stat().st_mode & 0o777)
            else:
                snapshot[path] = (None, 0o644)
        return snapshot

    def _restore_snapshot(self, snapshot: dict[Path, tuple[bytes | None, int]]) -> None:
        for path, (content, mode) in snapshot.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                self._atomic_write(path, content, default_mode=mode)
                os.chmod(path, mode)

    def _verify_backend(self, backend: DhcpBackend) -> None:
        service = self.system.selected_service(backend)
        state, _ = self.system.service_state(service)
        if state != "active":
            raise RuntimeError(f"DHCP service is {state} after configuration change")
        definition = self.system.definitions[backend]
        ok, output = self.system.validate_candidate(backend, definition.config_path)
        if not ok:
            raise RuntimeError(output or "DHCP configuration did not pass native validation")

    def _restart_and_verify(self, backend: DhcpBackend) -> None:
        result = self.system.service_action(backend, "reload")
        if result.returncode != 0:
            result = self.system.service_action(backend, "restart")
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or result.stdout.strip() or "DHCP service reload/restart failed"))
        self._verify_backend(backend)

    def _restart_previous_and_verify(self, backend: DhcpBackend) -> None:
        result = self.system.service_action(backend, "restart")
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or result.stdout.strip() or "DHCP rollback restart failed"))
        self._verify_backend(backend)

    def apply_configuration(self, config: DhcpConfiguration, actor: str) -> dict[str, Any]:
        with self._lock:
            validation = self.validate_configuration(config)
            if not validation.ok:
                raise DhcpConflictError("; ".join(item.message for item in validation.issues if item.level == "error"))
            backend = validation.backend
            if backend == DhcpBackend.none:
                raise RuntimeError("Install Kea DHCP4 before applying configuration")
            self.create_backup(actor, "Automatic backup before Apply", automatic=True)
            contents = self._target_contents(backend, config)
            snapshot = self._snapshot(list(contents))
            state_snapshot = self._snapshot([self.state_path])
            try:
                for path, content in contents.items():
                    self._atomic_write(path, content)
                self._restart_and_verify(backend)
                self._write_state(config, backend, actor)
            except Exception as error:
                self._restore_snapshot(snapshot)
                self._restore_snapshot(state_snapshot)
                try:
                    self._restart_previous_and_verify(backend)
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"{redact(str(error))}; rollback failed: {redact(str(rollback_error))}"
                    ) from rollback_error
                raise
            return {"configuration": config.model_dump(mode="json"), "validation": validation.model_dump(mode="json"), "backup_created": True}

    def _backup_payload_files(self, backup_dir: Path) -> list[Path]:
        return sorted(path for path in backup_dir.iterdir() if path.is_file() and path.name != "metadata.json")

    @staticmethod
    def _checksum_files(paths: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in sorted(paths, key=lambda item: item.name):
            digest.update(path.name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        backend = self.backend()
        backup_id = f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid4().hex[:8]}"
        target = self.backups_root / backup_id
        target.mkdir(mode=0o700)
        os.chmod(target, 0o700)
        files: list[Path] = []
        state = self._read_state()
        state_target = target / "webnas-state.json"
        state_target.write_text(json.dumps(state or {"configuration": self.configuration().model_dump(mode="json")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(state_target, 0o600)
        files.append(state_target)
        definition = self.system.definitions.get(backend)
        if definition:
            for label, source in (("dhcp-config", definition.config_path), ("interfaces-config", definition.interface_config_path)):
                if source and source.is_file():
                    suffix = source.suffix or ".conf"
                    destination = target / f"{label}{suffix}"
                    destination.write_bytes(source.read_bytes())
                    os.chmod(destination, 0o600)
                    files.append(destination)
        checksum = self._checksum_files(files)
        metadata = {
            "id": backup_id, "backend": backend.value, "version": self.system.version(backend), "timestamp": time.time(),
            "actor": actor, "description": description, "automatic": automatic, "sha256": checksum,
            "files": [path.name for path in files], "subnets": len(self.configuration().subnets), "reservations": len(self.configuration().reservations),
        }
        metadata_path = target / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(metadata_path, 0o600)
        if automatic:
            automatic_backups = [item for item in self.list_backups() if item.get("automatic")]
            for item in automatic_backups[20:]:
                shutil.rmtree(self.backups_root / str(item["id"]), ignore_errors=True)
        return metadata

    def list_backups(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for directory in self.backups_root.iterdir():
            metadata_path = directory / "metadata.json"
            if not directory.is_dir() or not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(metadata, dict):
                    values.append(metadata)
            except (OSError, ValueError):
                continue
        return sorted(values, key=lambda item: float(item.get("timestamp") or 0), reverse=True)

    def _verified_backup(self, backup_id: str) -> tuple[Path, dict[str, Any]]:
        if not backup_id or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for character in backup_id):
            raise ValueError("invalid backup identifier")
        directory = self.backups_root / backup_id
        metadata_path = directory / "metadata.json"
        if not directory.is_dir() or not metadata_path.is_file():
            raise DhcpNotFoundError("backup not found")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        files = self._backup_payload_files(directory)
        if self._checksum_files(files) != str(metadata.get("sha256") or ""):
            raise DhcpConflictError("backup checksum verification failed")
        return directory, metadata

    def restore_backup(self, backup_id: str, actor: str) -> dict[str, Any]:
        directory, metadata = self._verified_backup(backup_id)
        backend = DhcpBackend(str(metadata.get("backend") or "none"))
        if backend == DhcpBackend.none or backend != self.backend():
            raise DhcpConflictError("backup backend does not match the currently installed DHCP backend")
        self.create_backup(actor, f"Automatic safety backup before restore {backup_id}", automatic=True)
        definition = self.system.definitions[backend]
        candidates = [path for path in directory.iterdir() if path.is_file()]
        native = next((path for path in candidates if path.name.startswith("dhcp-config")), None)
        state_file = directory / "webnas-state.json"
        interfaces = next((path for path in candidates if path.name.startswith("interfaces-config")), None)
        if not native or not state_file.is_file():
            raise DhcpConflictError("backup is missing required configuration files")
        targets = [definition.config_path]
        if backend == DhcpBackend.isc and definition.interface_config_path:
            targets.append(definition.interface_config_path)
        snapshot = self._snapshot(targets + [self.state_path])
        try:
            self._atomic_write(definition.config_path, native.read_bytes())
            if backend == DhcpBackend.isc and definition.interface_config_path and interfaces:
                self._atomic_write(definition.interface_config_path, interfaces.read_bytes())
            self._atomic_write(self.state_path, state_file.read_bytes(), default_mode=0o600)
            os.chmod(self.state_path, 0o600)
            self._restart_and_verify(backend)
            restored = self.configuration()
            validation = self.validate_configuration(restored)
            if not validation.ok:
                raise RuntimeError("restored DHCP configuration failed WebNAS validation")
        except Exception as error:
            self._restore_snapshot(snapshot)
            try:
                self._restart_previous_and_verify(backend)
            except Exception as rollback_error:
                raise RuntimeError(
                    f"{redact(str(error))}; restore rollback failed: {redact(str(rollback_error))}"
                ) from rollback_error
            raise
        return {"restored": backup_id, "backup_created": True}

    def delete_backup(self, backup_id: str) -> None:
        directory, _ = self._verified_backup(backup_id)
        shutil.rmtree(directory)

    def _mutated(self, operation: str, object_id: str = "", payload: dict[str, Any] | None = None) -> DhcpConfiguration:
        config = self.configuration().model_copy(deep=True)
        payload = payload or {}
        if operation == "subnet_create":
            subnet = DhcpSubnet.model_validate(payload["subnet"])
            if any(item.id == subnet.id for item in config.subnets):
                raise DhcpConflictError("subnet identifier already exists")
            config.subnets.append(subnet)
        elif operation == "subnet_update":
            subnet = DhcpSubnet.model_validate(payload["subnet"])
            index = next((index for index, item in enumerate(config.subnets) if item.id == object_id), None)
            if index is None:
                raise DhcpNotFoundError("subnet not found")
            if subnet.id != object_id:
                raise DhcpConflictError("subnet identifier cannot be changed")
            config.subnets[index] = subnet
        elif operation == "subnet_delete":
            if any(item.subnet_id == object_id for item in config.reservations):
                raise DhcpConflictError("remove or move reservations before deleting the subnet")
            previous = len(config.subnets)
            config.subnets = [item for item in config.subnets if item.id != object_id]
            if len(config.subnets) == previous:
                raise DhcpNotFoundError("subnet not found")
        elif operation in {"subnet_enable", "subnet_disable"}:
            target_subnet = next((item for item in config.subnets if item.id == object_id), None)
            if not target_subnet:
                raise DhcpNotFoundError("subnet not found")
            target_subnet.enabled = operation == "subnet_enable"
        elif operation == "subnet_clone":
            source = next((item for item in config.subnets if item.id == object_id), None)
            if not source:
                raise DhcpNotFoundError("subnet not found")
            clone = source.model_copy(deep=True)
            clone.id = str(payload.get("new_id") or uuid4().hex)
            clone.name = str(payload.get("name") or f"{source.name} copy")[:128]
            clone.enabled = False
            config.subnets.append(clone)
        elif operation == "reservation_create":
            reservation = DhcpReservation.model_validate(payload["reservation"])
            if any(item.id == reservation.id for item in config.reservations):
                raise DhcpConflictError("reservation identifier already exists")
            config.reservations.append(reservation)
        elif operation == "reservation_update":
            reservation = DhcpReservation.model_validate(payload["reservation"])
            index = next((index for index, item in enumerate(config.reservations) if item.id == object_id), None)
            if index is None:
                raise DhcpNotFoundError("reservation not found")
            if reservation.id != object_id:
                raise DhcpConflictError("reservation identifier cannot be changed")
            config.reservations[index] = reservation
        elif operation == "reservation_delete":
            previous = len(config.reservations)
            config.reservations = [item for item in config.reservations if item.id != object_id]
            if len(config.reservations) == previous:
                raise DhcpNotFoundError("reservation not found")
        elif operation in {"reservation_enable", "reservation_disable"}:
            target_reservation = next((item for item in config.reservations if item.id == object_id), None)
            if not target_reservation:
                raise DhcpNotFoundError("reservation not found")
            target_reservation.enabled = operation == "reservation_enable"
        else:
            raise ValueError("unsupported DHCP configuration operation")
        return config

    def mutate_configuration(self, operation: str, object_id: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        config = self._mutated(operation, object_id, payload)
        plan = self.plan(config)
        if not plan.validation.ok:
            raise DhcpConflictError("; ".join(item.message for item in plan.validation.issues if item.level == "error"))
        result = self.apply_configuration(config, actor)
        return {**result, "plan": plan.model_dump(mode="json")}

    def convert_lease(self, lease_id: str, values: dict[str, Any], actor: str) -> dict[str, Any]:
        lease = next((item for item in self._leases_with_metadata() if item.id == lease_id), None)
        if not lease or lease.state != "active":
            raise DhcpNotFoundError("active lease not found")
        if not lease.mac_address or not lease.subnet_id:
            raise DhcpConflictError("lease does not contain a MAC address and managed subnet")
        hostname = str(values.get("hostname") or lease.hostname or f"host-{lease.ipv4_address.replace('.', '-')}")
        dns_provider_raw = str(values.get("dns_provider") or "auto")
        dns_provider = cast(Literal["auto", "pihole", "adguard-home"], dns_provider_raw if dns_provider_raw in {"auto", "pihole", "adguard-home"} else "auto")
        reservation = DhcpReservation(
            id=uuid4().hex, hostname=hostname, mac_address=lease.mac_address, ipv4_address=lease.ipv4_address,
            subnet_id=lease.subnet_id, description=str(values.get("description") or "Converted from active DHCP lease"),
            client_identifier=lease.client_identifier, create_dns_record=bool(values.get("create_dns_record")),
            dns_provider=dns_provider,
        )
        config = self.configuration().model_copy(deep=True)
        subnet = next((item for item in config.subnets if item.id == lease.subnet_id), None)
        if not subnet:
            raise DhcpNotFoundError("managed subnet not found")
        start, end = self._pool_bounds(subnet)
        address = int(ipaddress.ip_address(lease.ipv4_address))
        if start <= address <= end:
            raise DhcpConflictError("lease address is inside the dynamic pool; shrink or split the pool before converting it to a reservation")
        config.reservations.append(reservation)
        result = self.apply_configuration(config, actor)
        dns = self._sync_dns(reservation) if reservation.create_dns_record else None
        return {**result, "reservation": reservation.model_dump(mode="json"), "dns": dns}

    def add_lease_to_hosts(self, lease_id: str, actor: str, ssh_user: str = "algen-ansible") -> dict[str, Any]:
        lease = next((item for item in self._leases_with_metadata() if item.id == lease_id), None)
        if not lease:
            raise DhcpNotFoundError("lease not found")
        existing = find_host(address=lease.ipv4_address, variable_key="dhcp_mac", variable_value=lease.mac_address)
        variables = dict(existing.get("variables") or {}) if existing else {}
        variables.update({
            "dhcp_ip": lease.ipv4_address, "dhcp_mac": lease.mac_address, "dhcp_subnet": lease.subnet,
            "dhcp_subnet_id": lease.subnet_id, "dhcp_lease_state": lease.state,
            "dhcp_reservation_state": "reserved" if lease.reserved else "dynamic", "dhcp_source": "DHCP",
        })
        if not existing:
            variables["algen_provider"] = "dhcp"
        name = (existing.get("name") if existing else lease.hostname) or f"dhcp-{lease.ipv4_address.replace('.', '-')}"
        hostname = str(existing.get("hostname") or lease.hostname or "") if existing else lease.hostname
        payload = HostInput(
            name=str(name)[:128], hostname=hostname, fqdn=str(existing.get("fqdn") or "") if existing else "",
            address=lease.ipv4_address, management_address=str(existing.get("management_address") or "") if existing else "",
            port=int(existing.get("port") or 22) if existing else 22,
            connection_type=ConnectionType(str(existing.get("connection_type") or ConnectionType.ssh)) if existing else ConnectionType.ssh,
            ssh_user=str(existing.get("ssh_user") or ssh_user) if existing else ssh_user,
            credential_id=existing.get("credential_id") if existing else None,
            python_interpreter=str(existing.get("python_interpreter") or "auto_silent") if existing else "auto_silent",
            environment=str(existing.get("environment") or "") if existing else "", location=str(existing.get("location") or "") if existing else "",
            description=str(existing.get("description") or "") if existing else "Discovered through DHCP Manager",
            tags=list(existing.get("tags") or []) if existing else ["dhcp"], variables=variables,
            group_ids=list(existing.get("group_ids") or []) if existing else [], active=bool(existing.get("active", True)) if existing else True,
            approved=bool(existing.get("approved", False)) if existing else False, power_profile_id=existing.get("power_profile_id") if existing else None,
        )
        return hosts_registry().save_host(payload, actor, str(existing["id"]) if existing else None, source="dhcp")

    def reservation_from_host(self, host_id: str, subnet_id: str, mac_address: str, hostname: str, create_dns_record: bool, dns_provider: str, actor: str) -> dict[str, Any]:
        host = hosts_registry().host(host_id)
        if not host:
            raise DhcpNotFoundError("host not found")
        config = self.configuration().model_copy(deep=True)
        subnet = next((item for item in config.subnets if item.id == subnet_id), None)
        if not subnet:
            raise DhcpNotFoundError("subnet not found")
        dns_provider_value = cast(Literal["auto", "pihole", "adguard-home"], dns_provider if dns_provider in {"auto", "pihole", "adguard-home"} else "auto")
        reservation = DhcpReservation(
            id=uuid4().hex, hostname=hostname or str(host.get("hostname") or host.get("name") or "host"), mac_address=mac_address,
            ipv4_address=str(host["address"]), subnet_id=subnet_id, description=f"Created from Hosts Manager host {host_id}",
            create_dns_record=create_dns_record, dns_provider=dns_provider_value,
        )
        config.reservations.append(reservation)
        result = self.apply_configuration(config, actor)
        dns = self._sync_dns(reservation) if reservation.create_dns_record else None
        return {**result, "reservation": reservation.model_dump(mode="json"), "dns": dns}

    @staticmethod
    def _sync_dns(reservation: DhcpReservation) -> dict[str, Any]:
        providers = [reservation.dns_provider] if reservation.dns_provider != "auto" else ["pihole", "adguard-home"]
        errors: list[str] = []
        for module_id in providers:
            try:
                return upsert_dns_record(module_id, reservation.hostname, reservation.ipv4_address)
            except Exception as error:  # noqa: BLE001 - optional integration must not break DHCP.
                errors.append(redact(str(error))[:500])
        return {"updated": False, "provider": "", "warning": "; ".join(errors) or "No configured DNS integration is available"}

    def service_control(self, action: str) -> dict[str, Any]:
        backend = self.backend()
        if backend == DhcpBackend.none:
            raise RuntimeError("DHCP backend is not installed")
        result = self.system.service_action(backend, action)
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.strip() or result.stdout.strip() or f"DHCP service {action} failed"))
        service = self.system.selected_service(backend)
        state, enabled = self.system.service_state(service)
        return {"action": action, "backend": backend.value, "service_state": state, "service_enabled": enabled}

    def logs(self, **filters: Any) -> dict[str, Any]:
        return self.system.logs(self.backend(), **filters)

    def diagnostics(self, *, installed: bool, blocked_by_proxmox: bool) -> list[DhcpDiagnostic]:
        backend = self.backend()
        config = self.configuration()
        validation = self.validate_configuration(config, native=backend != DhcpBackend.none)
        service = self.system.selected_service(backend)
        state, enabled = self.system.service_state(service) if service else ("not_installed", False)
        interfaces = {item.name: item for item in self.interfaces()}
        utilization = self.utilization(config)
        result = [
            DhcpDiagnostic(status="PASS" if installed else "FAIL", code="package", title="DHCP Manager package", detail="installed" if installed else "not installed"),
            DhcpDiagnostic(status="PASS" if backend != DhcpBackend.none else "FAIL", code="backend", title="DHCP backend", detail=f"{backend.value} {self.system.version(backend)}".strip(), recommendation="Install Kea DHCP4" if backend == DhcpBackend.none else ""),
            DhcpDiagnostic(status="PASS" if validation.ok else "FAIL", code="config", title="Configuration syntax", detail="valid" if validation.ok else "; ".join(item.message for item in validation.issues if item.level == "error")[:2000]),
            DhcpDiagnostic(status="PASS" if state == "active" else "FAIL", code="service", title="Service state", detail=state),
            DhcpDiagnostic(status="PASS" if enabled else "WARNING", code="autostart", title="Service autostart", detail="enabled" if enabled else "disabled"),
            DhcpDiagnostic(status="FAIL" if blocked_by_proxmox else "PASS", code="proxmox-safe-mode", title="Proxmox Safe Mode", detail="mutations blocked" if blocked_by_proxmox else "standard host policy"),
            DhcpDiagnostic(status="PASS" if self.system.udp67_listening() else "WARNING", code="udp67", title="UDP 67 listener", detail="listening" if self.system.udp67_listening() else "no listener detected"),
        ]
        missing = [name for name in config.interfaces if name not in interfaces]
        result.append(DhcpDiagnostic(status="PASS" if not missing else "FAIL", code="interfaces", title="Listening interfaces", detail="all available" if not missing else f"missing: {', '.join(missing)}"))
        exhausted = [item for item in utilization if item.usage_percent > config.thresholds.emergency]
        result.append(DhcpDiagnostic(status="PASS" if not exhausted else "WARNING", code="pool-utilization", title="Pool exhaustion", detail="normal" if not exhausted else ", ".join(f"{item.subnet} {item.usage_percent}%" for item in exhausted)))
        dns_servers = list(dict.fromkeys(server for subnet in config.subnets for server in subnet.dns_servers))
        dns_ok = True
        if dns_servers:
            dns_ok = all(self._dns_reachable(server) for server in dns_servers[:4])
        result.append(DhcpDiagnostic(status="PASS" if dns_ok else "WARNING", code="dns-reachability", title="DNS reachability", detail="reachable or not configured" if dns_ok else "one or more configured DNS servers did not answer"))
        result.append(DhcpDiagnostic(status="PASS" if self.system.firewall_state() != "unknown" else "WARNING", code="firewall", title="Firewall state", detail=self.system.firewall_state()))
        definition = self.system.definitions.get(backend)
        ownership_ok, permission_ok = True, True
        if definition and definition.config_path.exists():
            file_stat = definition.config_path.stat()
            ownership_ok = file_stat.st_uid == 0
            permission_ok = not bool(file_stat.st_mode & stat.S_IWOTH)
        result.append(DhcpDiagnostic(status="PASS" if ownership_ok else "WARNING", code="ownership", title="Configuration ownership", detail="root-owned" if ownership_ok else "configuration is not root-owned"))
        result.append(DhcpDiagnostic(status="PASS" if permission_ok else "FAIL", code="permissions", title="Configuration permissions", detail="not world-writable" if permission_ok else "configuration is world-writable"))
        return result

    @staticmethod
    def _dns_reachable(address: str) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            try:
                sock.connect((address, 53))
                return True
            finally:
                sock.close()
        except OSError:
            return False


_service: DhcpService | None = None
_service_lock = threading.Lock()


def service() -> DhcpService:
    global _service
    with _service_lock:
        if _service is None:
            _service = DhcpService()
        return _service
