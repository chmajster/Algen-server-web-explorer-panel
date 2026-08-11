"""Typed, safety-oriented Docker management API."""

from . import models as _models
from .container_action_models import ContainerActionRequest as _ContainerActionRequest
from .host_network_models import ContainerCreateRequest as _HostNetworkContainerCreateRequest

setattr(_models, "ContainerCreateRequest", _HostNetworkContainerCreateRequest)
setattr(_models, "ContainerActionRequest", _ContainerActionRequest)

del _ContainerActionRequest
del _HostNetworkContainerCreateRequest
