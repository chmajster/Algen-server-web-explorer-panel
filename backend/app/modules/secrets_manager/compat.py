from __future__ import annotations

from typing import Any

_installed = False
_originals: dict[str, Any] = {}


def _host_registry_class() -> type:
    from ..hosts_manager.public import registry as hosts_registry

    return type(hosts_registry())


def install_hosts_credential_compatibility() -> bool:
    """Redirect the legacy Hosts Manager credential surface to Secrets Manager.

    The Hosts Manager SQLite credential rows remain only for rollback and local
    foreign-key compatibility. No runtime secret read or write uses them after
    this adapter is installed.
    """
    global _installed
    if _installed:
        return True

    from .service import service

    secrets_service = service()
    if secrets_service.migration_error:
        return False
    host_registry_class = _host_registry_class()

    for name in ("credentials", "save_credential", "verified_credential", "delete_credential"):
        _originals.setdefault(name, getattr(host_registry_class, name))

    def credentials(self: Any) -> list[dict[str, Any]]:
        return service().credentials()

    def save_credential(self: Any, payload: Any, actor: str, credential_id: str | None = None) -> dict[str, Any]:
        return service().save_credential(payload, actor, credential_id)

    def verified_credential(self: Any, credential_id: str, *, module_id: str, purpose: str) -> dict[str, str]:
        return service().verified_credential(credential_id, module_id=module_id, purpose=purpose)

    def delete_credential(self: Any, credential_id: str) -> bool:
        return service().delete_credential(credential_id)

    setattr(host_registry_class, "credentials", credentials)
    setattr(host_registry_class, "save_credential", save_credential)
    setattr(host_registry_class, "verified_credential", verified_credential)
    setattr(host_registry_class, "delete_credential", delete_credential)
    _installed = True
    return True


def uninstall_hosts_credential_compatibility() -> None:
    global _installed
    if not _installed:
        return
    host_registry_class = _host_registry_class()
    for name, method in _originals.items():
        setattr(host_registry_class, name, method)
    _installed = False


def startup() -> None:
    # A failed migration intentionally leaves the legacy runtime untouched.
    install_hosts_credential_compatibility()


def shutdown() -> None:
    # Do not switch a live process back to the legacy vault during normal
    # shutdown ordering. The process is exiting and rollback is startup-driven.
    return None
