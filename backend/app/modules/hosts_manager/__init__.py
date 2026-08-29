"""Central host registry used by WebNAS modules."""

from . import service as _service
from .batch_enrichment import HostRegistryService, registry

# Keep historical imports from ``hosts_manager.service`` compatible while the
# optimized implementation lives behind the package boundary. Importing the
# package always precedes importing one of its submodules, so consumers receive
# the same optimized class regardless of the supported import path they use.
setattr(_service, "HostRegistryService", HostRegistryService)
setattr(_service, "registry", registry)

__all__ = ["HostRegistryService", "registry"]
