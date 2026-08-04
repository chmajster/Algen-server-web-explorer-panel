"""Typed, safety-oriented Docker management API."""

# ContainerCreateRequest originally forbids Docker's host network mode.
# Install the compatible model before router.py or public.py imports it.
from . import models as _models
from .host_network_models import ContainerCreateRequest as _HostNetworkContainerCreateRequest

_models.ContainerCreateRequest = _HostNetworkContainerCreateRequest

del _HostNetworkContainerCreateRequest
