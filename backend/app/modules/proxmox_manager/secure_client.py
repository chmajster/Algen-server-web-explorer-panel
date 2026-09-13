from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import service as _service


_ORIGINAL_URLOPEN = urllib.request.urlopen


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class HardenedProxmoxApiClient(_service.ProxmoxApiClient):
    def _open_no_redirect(self, request: urllib.request.Request):
        # Preserve explicit runtime/test instrumentation that replaces urlopen,
        # while normal production traffic always goes through a redirect-blocking opener.
        current_urlopen = _service.urllib.request.urlopen
        if current_urlopen is not _ORIGINAL_URLOPEN:
            return current_urlopen(request, timeout=self.timeout, context=self.ssl_context)
        opener = urllib.request.build_opener(
            urllib.request.HTTPHandler(),
            urllib.request.HTTPSHandler(context=self.ssl_context),
            _NoRedirectHandler(),
        )
        return opener.open(request, timeout=self.timeout)

    def _login(self) -> None:
        encoded = urllib.parse.urlencode({"username": self.username, "password": self.secret}).encode()
        request = urllib.request.Request(
            f"{self.endpoint}/api2/json/access/ticket",
            data=encoded,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._open_no_redirect(request) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = _service._http_failure_detail(error)
            reason = f"HTTP {error.code}" + (f": {detail}" if detail else "")
            hint = _service._http_failure_hint(error.code)
            raise _service.ProxmoxApiError(
                _service._failure_message("login", self.endpoint, "login", reason, hint),
                status=error.code,
                stage="login",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as error:
            stage, reason, hint = _service._network_failure_details(error)
            raise _service.ProxmoxApiError(
                _service._failure_message("login", self.endpoint, stage, reason, hint),
                stage=stage,
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            ) from error
        except (ValueError, UnicodeDecodeError) as error:
            reason = f"Invalid login response: {type(error).__name__}: {_service._safe_error_text(error)}"
            hint = "Verify that the configured address and port expose the Proxmox API rather than another web service."
            raise _service.ProxmoxApiError(
                _service._failure_message("login", self.endpoint, "login", reason, hint),
                stage="login",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            ) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("ticket") or not data.get("CSRFPreventionToken"):
            reason = "Proxmox login returned an invalid response without a ticket and CSRF token"
            hint = "Verify the endpoint, reverse proxy configuration, and Proxmox authentication service."
            raise _service.ProxmoxApiError(
                _service._failure_message("login", self.endpoint, "login", reason, hint),
                stage="login",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            )
        self.ticket = str(data["ticket"])
        self.csrf_token = str(data["CSRFPreventionToken"])

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        encoded = urllib.parse.urlencode(data or {}, doseq=True).encode() if method != "GET" else None
        url = f"{self.endpoint}/api2/json/{path.lstrip('/')}"
        headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        if self.credential_type == "proxmox_api":
            headers["Authorization"] = self.authorization
        else:
            if not self.ticket:
                self._login()
            headers["Cookie"] = f"PVEAuthCookie={self.ticket}"
            if method != "GET":
                headers["CSRFPreventionToken"] = self.csrf_token
        request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
        try:
            with self._open_no_redirect(request) as response:
                payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = _service._http_failure_detail(error)
            reason = f"HTTP {error.code}" + (f": {detail}" if detail else "")
            hint = _service._http_failure_hint(error.code)
            raise _service.ProxmoxApiError(
                _service._failure_message("API request", self.endpoint, "api", reason, hint),
                status=error.code,
                stage="api",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as error:
            stage, reason, hint = _service._network_failure_details(error)
            raise _service.ProxmoxApiError(
                _service._failure_message("API request", self.endpoint, stage, reason, hint),
                stage=stage,
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            ) from error
        if not isinstance(payload, dict) or "data" not in payload:
            reason = "Proxmox API returned a response without the expected data field"
            hint = "Verify that the configured address and port expose a compatible Proxmox API endpoint."
            raise _service.ProxmoxApiError(
                _service._failure_message("API request", self.endpoint, "api", reason, hint),
                stage="api",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            )
        return payload["data"]
