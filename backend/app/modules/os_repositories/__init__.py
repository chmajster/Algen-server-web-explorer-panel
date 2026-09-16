"""Central APT/RPM repository manager for WebNAS."""

MODULE_ID = "os-repositories"

# Install the manifest boundary before any offline-service consumer obtains the
# shared service class. The hardening wrapper is idempotent and performs no I/O.
from .offline_hardening import install_offline_hardening as _install_offline_hardening

_install_offline_hardening()
