from __future__ import annotations

import http.client
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from typing import Any

from . import service as _service


_ORIGINAL_URLOPEN = urllib.request.urlopen


class _ResponseTooLarge(ValueError):
    pass


def _read_json(response: Any, limit: int) -> Any:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise _ResponseTooLarge("Proxmox response exceeded the safety limit")
    return json.loads(body.decode("utf-8"))


def _login_header(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        return None
    return value


def _http_failure_detail(error: urllib.error.HTTPError) -> str:
    try:
        return _service._http_failure_detail(error)
    except (OSError, http.client.HTTPException, RecursionError):
        # Optional diagnostics must not replace the original HTTP status.
        return ""
    finally:
        with suppress(OSError, http.client.HTTPException):
            error.close()


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

    def _invalid_response_error(self, stage: str, error: BaseException) -> _service.ProxmoxApiError:
        operation = "login" if stage == "login" else "API request"
        reason = (
            "Proxmox response exceeded the safety limit"
            if isinstance(error, _ResponseTooLarge)
            else f"Invalid {stage} response: {type(error).__name__}"
        )
        hint = "Verify that the configured address and port expose the Proxmox API rather than another web service."
        return _service.ProxmoxApiError(
            _service._failure_message(operation, self.endpoint, stage, reason, hint),
            stage=stage,
            endpoint=self.endpoint,
            reason=reason,
            hint=hint,
        )

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
                payload = _read_json(response, 1024 * 1024)
        except urllib.error.HTTPError as error:
            detail = _http_failure_detail(error)
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
        except (ValueError, RecursionError, http.client.HTTPException) as error:
            raise self._invalid_response_error("login", error) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        ticket = _login_header(data.get("ticket")) if isinstance(data, dict) else None
        csrf_token = _login_header(data.get("CSRFPreventionToken")) if isinstance(data, dict) else None
        if ticket is None or csrf_token is None:
            reason = "Proxmox login returned an invalid response without a ticket and CSRF token"
            hint = "Verify the endpoint, reverse proxy configuration, and Proxmox authentication service."
            raise _service.ProxmoxApiError(
                _service._failure_message("login", self.endpoint, "login", reason, hint),
                stage="login",
                endpoint=self.endpoint,
                reason=reason,
                hint=hint,
            )
        self.ticket = ticket
        self.csrf_token = csrf_token

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
                payload = _read_json(response, 4 * 1024 * 1024)
        except urllib.error.HTTPError as error:
            detail = _http_failure_detail(error)
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
        except (ValueError, RecursionError, http.client.HTTPException) as error:
            raise self._invalid_response_error("api", error) from error
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
