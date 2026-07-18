from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class AwxClient:
    def __init__(self, url: str, token: str, *, verify_tls: bool = True, ca_certificate: str = "", timeout: int = 15) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("invalid AWX URL")
        self.base_url = url.rstrip("/")
        self.token = token
        self.timeout = min(max(timeout, 2), 120)
        if verify_tls:
            self.context = ssl.create_default_context(cadata=ca_certificate or None)
        else:
            self.context = ssl._create_unverified_context()  # noqa: S323 - explicit administrator option, disabled by default

    def request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith("/api/v2/") or ".." in path:
            raise ValueError("unsupported AWX API path")
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as response:  # nosec B310 - URL origin validated above
                value = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(f"AWX request failed: {error}") from error
        if not isinstance(value, dict):
            raise RuntimeError("AWX returned an invalid response")
        return value

    def ping(self) -> dict[str, Any]:
        return self.request("/api/v2/ping/")

    def list_resource(self, resource: str) -> list[dict[str, Any]]:
        allowed = {"organizations", "inventories", "projects", "job_templates"}
        if resource not in allowed:
            raise ValueError("unsupported AWX resource")
        value = self.request(f"/api/v2/{resource}/?page_size=200")
        results = value.get("results") or []
        return [item for item in results[:200] if isinstance(item, dict)]

    def launch(self, template_id: int) -> dict[str, Any]:
        if template_id <= 0:
            raise ValueError("invalid AWX job template id")
        return self.request(f"/api/v2/job_templates/{template_id}/launch/", method="POST", payload={})

    def job(self, job_id: int) -> dict[str, Any]:
        if job_id <= 0:
            raise ValueError("invalid AWX job id")
        return self.request(f"/api/v2/jobs/{job_id}/")

    def stdout(self, job_id: int) -> str:
        value = self.request(f"/api/v2/jobs/{job_id}/stdout/?format=json")
        return str(value.get("content") or "")[:512 * 1024]
