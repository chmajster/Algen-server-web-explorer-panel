from __future__ import annotations

from fastapi import APIRouter, Depends

from ...identity.permissions import authorize
from ...package_center.models import api_error
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .models import DnsLookupRequest, HttpTestRequest, PortTestRequest, ReverseDnsRequest, TargetRequest
from .rbac import NETWORK_TOOLS_CONNECTIONS, NETWORK_TOOLS_DNS, NETWORK_TOOLS_HTTP_TEST, NETWORK_TOOLS_PING, NETWORK_TOOLS_PORT_TEST, NETWORK_TOOLS_ROUTES, NETWORK_TOOLS_TRACEROUTE, NETWORK_TOOLS_VIEW
from .service import NetworkToolError, service


router = APIRouter(prefix="/api/modules/network-tools", tags=["network-tools"])
_PUBLIC_NETWORK_ERRORS = {"dig is required for this DNS record type", "iproute2 is unavailable"}
_RATE_NETWORK_ERRORS = {"network diagnostic rate limit exceeded", "too many concurrent network diagnostics"}


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _run(user: SessionUser, action: str, callback):  # type: ignore[no-untyped-def]
    try:
        return service().execute(user.username, action, callback)
    except NetworkToolError as error:
        message = str(error)
        if message in _RATE_NETWORK_ERRORS:
            api_error(429, "NETWORK_TOOL_FAILED", message)
        api_error(422, "NETWORK_TOOL_FAILED", message if message in _PUBLIC_NETWORK_ERRORS else "Network diagnostic failed")


@router.get("/overview")
def overview(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_VIEW)
    return _run(user, "overview", service().overview)


@router.post("/ping")
def ping(payload: TargetRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_PING)
    return _run(user, "ping", lambda: service().connectivity("ping", payload.target))


@router.post("/traceroute")
def traceroute(payload: TargetRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_TRACEROUTE)
    return _run(user, "traceroute", lambda: service().connectivity("trace", payload.target))


@router.post("/dns")
def dns(payload: DnsLookupRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_DNS)
    result = _run(user, "dns", lambda: service().dns_lookup(payload))
    if isinstance(result, dict) and result.get("error"):
        result = {**result, "error": "DNS lookup failed"}
    return result


@router.post("/reverse-dns")
def reverse_dns(payload: ReverseDnsRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_DNS)
    return _run(user, "reverse-dns", lambda: service().reverse_dns(payload.address))


@router.post("/port-test")
def port_test(payload: PortTestRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_PORT_TEST)
    return _run(user, "port-test", lambda: service().connectivity("tcp", payload.target, payload.port))


@router.post("/http-test")
def http_test(payload: HttpTestRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_HTTP_TEST)
    return _run(user, "http-test", lambda: service().http_test(payload))


@router.post("/route-lookup")
def route_lookup(payload: TargetRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, NETWORK_TOOLS_ROUTES)
    return _run(user, "route-lookup", lambda: service().route_lookup(payload.target))


@router.get("/routes")
def routes(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_ROUTES)
    from ...network_diagnostics import routing_snapshot
    return routing_snapshot()


@router.get("/neighbors")
def neighbors(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_VIEW)
    return service().neighbors()


@router.get("/interfaces")
def interfaces(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_VIEW)
    from ...network_diagnostics import network_overview
    return network_overview()


@router.get("/connections")
def connections(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_CONNECTIONS)
    return service().connections()


@router.get("/listening-ports")
def listening_ports(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_CONNECTIONS)
    from ..firewall_manager import service as firewall_service
    values = firewall_service().listening_ports()
    return {"items": values, "total": len(values)}


@router.get("/dns-configuration")
def dns_config(user: SessionUser = Depends(current_user)):
    _allow(user, NETWORK_TOOLS_DNS)
    from ...network_diagnostics import dns_configuration
    return dns_configuration()
