from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import queue
import socket
import sqlite3
import ssl
import threading
import time
import urllib.parse
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Any

from ...config import get_config
from ...core.events import bus
from ..ansible_controller.public_security import redact, redact_text
from ..secrets_manager.public import secret_metadata, verified_secret
from .events import event_types, on_event_registered, register_event_type
from .models import WebhookInput


class ClosingConnection(sqlite3.Connection):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:  # type: ignore[override]
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _id() -> str:
    return os.urandom(16).hex()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class WebhookValidationError(ValueError):
    pass


class WebhookManagerService:
    def __init__(self, path: Path | None = None) -> None:
        root = (path.parent if path else Path(get_config().paths.data_dir) / "webhook-manager").resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.path = path or root / "webhooks.sqlite3"
        self._lock = threading.RLock()
        self._queue: queue.Queue[tuple[str, str, str, dict[str, Any]] | None] = queue.Queue(maxsize=10_000)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._unsubscribers: dict[str, Any] = {}
        self._event_listener_unsubscribe: Any = None
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS webhooks(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    url TEXT NOT NULL,
                    method TEXT NOT NULL DEFAULT 'POST',
                    events_json TEXT NOT NULL DEFAULT '[]',
                    timeout_seconds REAL NOT NULL DEFAULT 10,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    headers_json TEXT NOT NULL DEFAULT '{}',
                    auth_type TEXT NOT NULL DEFAULT 'none',
                    secret_id TEXT,
                    auth_header_name TEXT NOT NULL DEFAULT 'X-API-Key',
                    signing_secret_id TEXT,
                    allow_private_networks INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_wh_enabled ON webhooks(enabled,name);
                CREATE TABLE IF NOT EXISTS deliveries(
                    id TEXT PRIMARY KEY,
                    webhook_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    error_category TEXT NOT NULL DEFAULT '',
                    response_preview TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_wh_delivery_time ON deliveries(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wh_delivery_webhook ON deliveries(webhook_id,created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wh_delivery_event ON deliveries(event_id,attempt);
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _decode_json(value: Any, fallback: Any) -> Any:
        try:
            return json.loads(str(value or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def _metadata(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "description": str(item.get("description") or ""),
            "enabled": bool(item.get("enabled", 1)),
            "url": str(item["url"]),
            "method": str(item["method"]),
            "events": self._decode_json(item.get("events_json"), []),
            "timeout_seconds": float(item.get("timeout_seconds") or 10),
            "max_attempts": int(item.get("max_attempts") or 1),
            "headers": self._decode_json(item.get("headers_json"), {}),
            "auth_type": str(item.get("auth_type") or "none"),
            "secret_id": item.get("secret_id"),
            "auth_header_name": str(item.get("auth_header_name") or "X-API-Key"),
            "signing_secret_id": item.get("signing_secret_id"),
            "allow_private_networks": bool(item.get("allow_private_networks")),
            "created_at": float(item.get("created_at") or 0),
            "updated_at": float(item.get("updated_at") or 0),
        }

    def webhooks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM webhooks ORDER BY name COLLATE NOCASE,id").fetchall()
        return [self._metadata(row) for row in rows]

    def webhook(self, webhook_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        return self._metadata(row) if row else None

    @staticmethod
    def _address_allowed(address: str, *, allow_private: bool) -> bool:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            return False
        return allow_private or not ip.is_private

    def validate_url(self, url: str, *, allow_private: bool) -> dict[str, Any]:
        try:
            parsed = urllib.parse.urlsplit(url.strip())
        except ValueError as error:
            raise WebhookValidationError("malformed webhook URL") from error
        if parsed.scheme not in {"http", "https"}:
            raise WebhookValidationError("webhook URL must use http or https")
        if not parsed.hostname:
            raise WebhookValidationError("webhook URL requires a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise WebhookValidationError("credentials are forbidden in webhook URLs")
        if parsed.fragment:
            raise WebhookValidationError("webhook URL fragments are not supported")
        host = parsed.hostname.strip().lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"}:
            raise WebhookValidationError("localhost webhook targets are forbidden")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as error:
            raise WebhookValidationError("invalid webhook port") from error
        if not 1 <= port <= 65535:
            raise WebhookValidationError("invalid webhook port")
        try:
            addresses = {str(ipaddress.ip_address(host))}
        except ValueError:
            try:
                addresses = {
                    str(ipaddress.ip_address(item[4][0]))
                    for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                }
            except (OSError, ValueError) as error:
                raise WebhookValidationError("webhook hostname could not be resolved") from error
        if not addresses:
            raise WebhookValidationError("webhook hostname resolved to no addresses")
        if any(not self._address_allowed(address, allow_private=allow_private) for address in addresses):
            raise WebhookValidationError("webhook target resolves to a blocked address range")
        return {
            "scheme": parsed.scheme,
            "hostname": host,
            "port": port,
            "resolved_addresses": sorted(addresses),
            "path": parsed.path or "/",
            "query": parsed.query,
        }

    @staticmethod
    def _validate_events(events: list[str]) -> None:
        unknown = sorted(set(events) - set(event_types()))
        if unknown:
            raise WebhookValidationError(f"unknown webhook event: {unknown[0]}")

    @staticmethod
    def _validate_secret_reference(secret_id: str | None) -> None:
        if not secret_id:
            return
        item = secret_metadata(secret_id)
        if not item:
            raise WebhookValidationError("selected secret does not exist")
        if "webhook-manager" not in item.get("shared_with", []):
            raise WebhookValidationError("selected secret is not shared with webhook-manager")

    def save(self, payload: WebhookInput, actor: str, webhook_id: str | None = None) -> dict[str, Any]:
        self.validate_url(payload.url, allow_private=payload.allow_private_networks)
        self._validate_events(payload.events)
        self._validate_secret_reference(payload.secret_id)
        self._validate_secret_reference(payload.signing_secret_id)
        if payload.auth_type != "none" and not payload.secret_id:
            raise WebhookValidationError("authentication requires a Secrets Manager secret")
        now = time.time()
        item_id = webhook_id or _id()
        with self._lock, self.connect() as connection:
            old = connection.execute("SELECT created_at,created_by FROM webhooks WHERE id=?", (item_id,)).fetchone()
            created_at = float(old["created_at"]) if old else now
            created_by = str(old["created_by"]) if old else actor
            try:
                connection.execute(
                    """
                    INSERT INTO webhooks(
                        id,name,description,enabled,url,method,events_json,timeout_seconds,max_attempts,headers_json,
                        auth_type,secret_id,auth_header_name,signing_secret_id,allow_private_networks,
                        created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,description=excluded.description,enabled=excluded.enabled,url=excluded.url,
                        method=excluded.method,events_json=excluded.events_json,timeout_seconds=excluded.timeout_seconds,
                        max_attempts=excluded.max_attempts,headers_json=excluded.headers_json,auth_type=excluded.auth_type,
                        secret_id=excluded.secret_id,auth_header_name=excluded.auth_header_name,
                        signing_secret_id=excluded.signing_secret_id,allow_private_networks=excluded.allow_private_networks,
                        updated_at=excluded.updated_at,updated_by=excluded.updated_by
                    """,
                    (
                        item_id,
                        payload.name,
                        payload.description,
                        int(payload.enabled),
                        payload.url,
                        payload.method,
                        _json(payload.events),
                        payload.timeout_seconds,
                        payload.max_attempts,
                        _json(payload.headers),
                        payload.auth_type,
                        payload.secret_id,
                        payload.auth_header_name,
                        payload.signing_secret_id,
                        int(payload.allow_private_networks),
                        created_at,
                        now,
                        created_by,
                        actor,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise WebhookValidationError("a webhook with this name already exists") from error
        item = self.webhook(item_id)
        if not item:
            raise RuntimeError("saved webhook is unavailable")
        return item

    def delete(self, webhook_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,)).rowcount > 0

    def set_enabled(self, webhook_id: str, enabled: bool, actor: str) -> dict[str, Any]:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE webhooks SET enabled=?,updated_at=?,updated_by=? WHERE id=?",
                (int(enabled), time.time(), actor, webhook_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("webhook not found")
        item = self.webhook(webhook_id)
        if not item:
            raise KeyError("webhook not found")
        return item

    def deliveries(self, *, webhook_id: str = "", status: str = "", limit: int = 250) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if webhook_id:
            clauses.append("webhook_id=?")
            params.append(webhook_id)
        if status:
            if status not in {"success", "failed", "retry"}:
                raise WebhookValidationError("invalid delivery status")
            clauses.append("status=?")
            params.append(status)
        query = "SELECT * FROM deliveries"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def dashboard(self) -> dict[str, Any]:
        since = time.time() - 86400
        with self.connect() as connection:
            enabled = int(connection.execute("SELECT COUNT(*) FROM webhooks WHERE enabled=1").fetchone()[0])
            rows = connection.execute(
                "SELECT status,COUNT(*) AS amount FROM deliveries WHERE created_at>=? GROUP BY status",
                (since,),
            ).fetchall()
        counts = {str(row["status"]): int(row["amount"]) for row in rows}
        return {
            "enabled_webhooks": enabled,
            "successful_deliveries_24h": counts.get("success", 0),
            "failed_deliveries_24h": counts.get("failed", 0),
            "retry_deliveries_24h": counts.get("retry", 0),
            "deliveries_24h": sum(counts.values()),
            "queue_depth": self._queue.qsize(),
        }

    @staticmethod
    def _canonical_payload(event_id: str, event_type: str, timestamp: int, payload: dict[str, Any]) -> bytes:
        return _json(
            {
                "delivery_id": event_id,
                "event": event_type,
                "timestamp": timestamp,
                "payload": redact(payload),
            }
        ).encode("utf-8")

    def _headers(
        self,
        webhook: dict[str, Any],
        *,
        event_id: str,
        event_type: str,
        timestamp: int,
        body: bytes,
    ) -> dict[str, str]:
        headers = {str(key): str(value) for key, value in dict(webhook.get("headers") or {}).items()}
        headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "WebNAS-Webhook-Manager/1.0",
                "X-WebNAS-Event": event_type,
                "X-WebNAS-Delivery": event_id,
                "X-WebNAS-Timestamp": str(timestamp),
            }
        )
        if webhook.get("auth_type") != "none":
            credential = verified_secret(
                str(webhook.get("secret_id")),
                module_id="webhook-manager",
                purpose=f"webhook-auth:{webhook['id']}",
            )
            auth_type = str(webhook["auth_type"])
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {credential['secret']}"
            elif auth_type == "basic":
                token = base64.b64encode(
                    f"{credential['username']}:{credential['secret']}".encode()
                ).decode("ascii")
                headers["Authorization"] = f"Basic {token}"
            elif auth_type in {"api_key_header", "secret_header"}:
                headers[str(webhook.get("auth_header_name") or "X-API-Key")] = credential["secret"]
            else:
                raise WebhookValidationError("unsupported webhook authentication type")
        if webhook.get("signing_secret_id"):
            signing = verified_secret(
                str(webhook["signing_secret_id"]),
                module_id="webhook-manager",
                purpose=f"webhook-signing:{webhook['id']}",
            )
            digest = hmac.new(
                signing["secret"].encode("utf-8"),
                str(timestamp).encode("ascii") + b"." + body,
                hashlib.sha256,
            ).hexdigest()
            headers["X-WebNAS-Signature"] = f"sha256={digest}"
        return headers

    def _record_delivery(
        self,
        *,
        delivery_id: str,
        webhook_id: str,
        event_id: str,
        event_type: str,
        attempt: int,
        status: str,
        http_status: int | None,
        duration_ms: float,
        error_category: str,
        response_preview: str,
    ) -> dict[str, Any]:
        safe_preview = redact_text(response_preview[:2048])
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO deliveries(
                    id,webhook_id,event_id,event_type,attempt,status,http_status,duration_ms,error_category,response_preview,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    delivery_id,
                    webhook_id,
                    event_id,
                    event_type,
                    attempt,
                    status,
                    http_status,
                    duration_ms,
                    error_category[:120],
                    safe_preview,
                    time.time(),
                ),
            )
        return {
            "id": delivery_id,
            "webhook_id": webhook_id,
            "event_id": event_id,
            "event_type": event_type,
            "attempt": attempt,
            "status": status,
            "http_status": http_status,
            "duration_ms": round(duration_ms, 2),
            "error_category": error_category,
            "response_preview": safe_preview,
        }

    @staticmethod
    def _host_header(hostname: str, port: int, scheme: str) -> str:
        host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        return host if port == default_port else f"{host}:{port}"

    def _pinned_request(
        self,
        *,
        validation: dict[str, Any],
        method: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, str]:
        scheme = str(validation["scheme"])
        hostname = str(validation["hostname"])
        port = int(validation["port"])
        path = str(validation.get("path") or "/")
        query = str(validation.get("query") or "")
        target = f"{path}?{query}" if query else path
        request_headers = dict(headers)
        request_headers["Host"] = self._host_header(hostname, port, scheme)
        request_headers["Content-Length"] = str(len(body))
        request_headers["Connection"] = "close"

        try:
            header_lines = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
            request_bytes = (
                f"{method} {target} HTTP/1.1\r\n{header_lines}\r\n".encode("latin-1") + body
            )
        except UnicodeEncodeError as error:
            raise WebhookValidationError("webhook headers must use ISO-8859-1 characters") from error

        last_error: OSError | None = None
        for address in validation["resolved_addresses"]:
            raw_socket: socket.socket | None = None
            transport: socket.socket | None = None
            response: http.client.HTTPResponse | None = None
            try:
                raw_socket = socket.create_connection((str(address), port), timeout=timeout)
                transport = raw_socket
                if scheme == "https":
                    context = ssl.create_default_context()
                    context.minimum_version = ssl.TLSVersion.TLSv1_2
                    transport = context.wrap_socket(raw_socket, server_hostname=hostname)
                transport.settimeout(timeout)
                transport.sendall(request_bytes)
                response = http.client.HTTPResponse(transport)
                response.begin()
                status = int(response.status)
                preview = response.read(2048).decode("utf-8", errors="replace")
                return status, preview
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = OSError(str(error))
            finally:
                if response is not None:
                    response.close()
                if transport is not None:
                    transport.close()
                elif raw_socket is not None:
                    raw_socket.close()
        if last_error is not None:
            raise last_error
        raise OSError("webhook target has no validated address")

    def _deliver_once(
        self,
        webhook: dict[str, Any],
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        validation = self.validate_url(
            str(webhook["url"]),
            allow_private=bool(webhook.get("allow_private_networks")),
        )
        timestamp = int(time.time())
        body = self._canonical_payload(event_id, event_type, timestamp, payload)
        headers = self._headers(
            webhook,
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            body=body,
        )
        started = time.monotonic()
        status_code: int | None = None
        preview = ""
        error_category = ""
        success = False
        try:
            status_code, preview = self._pinned_request(
                validation=validation,
                method=str(webhook["method"]),
                headers=headers,
                body=body,
                timeout=float(webhook["timeout_seconds"]),
            )
            success = 200 <= status_code < 300
            if not success:
                error_category = "http_error"
        except (TimeoutError, OSError, ssl.SSLError, http.client.HTTPException) as error:
            error_category = type(error).__name__
        return self._record_delivery(
            delivery_id=_id(),
            webhook_id=str(webhook["id"]),
            event_id=event_id,
            event_type=event_type,
            attempt=attempt,
            status="success" if success else "failed",
            http_status=status_code,
            duration_ms=(time.monotonic() - started) * 1000,
            error_category=error_category,
            response_preview=preview,
        )

    def _deliver_with_retries(
        self,
        webhook_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        for attempt in range(1, 9):
            webhook = self.webhook(webhook_id)
            if not webhook or not webhook["enabled"]:
                return
            max_attempts = int(webhook["max_attempts"])
            if attempt > max_attempts:
                return
            try:
                result = self._deliver_once(webhook, event_id, event_type, payload, attempt)
            except Exception as error:  # noqa: BLE001 - delivery failure must not kill the worker
                result = self._record_delivery(
                    delivery_id=_id(),
                    webhook_id=webhook_id,
                    event_id=event_id,
                    event_type=event_type,
                    attempt=attempt,
                    status="failed",
                    http_status=None,
                    duration_ms=0,
                    error_category=type(error).__name__,
                    response_preview="",
                )
            if result["status"] == "success":
                return
            if attempt < max_attempts:
                with self.connect() as connection:
                    connection.execute("UPDATE deliveries SET status='retry' WHERE id=?", (result["id"],))
                if self._stop.wait(min(2 ** (attempt - 1), 30)):
                    return

    def enqueue_event(self, event_type: str, payload: dict[str, Any]) -> str:
        register_event_type(event_type)
        event_id = _id()
        safe_payload = redact(dict(payload))
        for webhook in self.webhooks():
            if webhook["enabled"] and event_type in webhook["events"]:
                try:
                    self._queue.put_nowait((str(webhook["id"]), event_id, event_type, safe_payload))
                except queue.Full:
                    self._record_delivery(
                        delivery_id=_id(),
                        webhook_id=str(webhook["id"]),
                        event_id=event_id,
                        event_type=event_type,
                        attempt=0,
                        status="failed",
                        http_status=None,
                        duration_ms=0,
                        error_category="queue_full",
                        response_preview="",
                    )
        return event_id

    def test(self, webhook_id: str) -> dict[str, Any]:
        webhook = self.webhook(webhook_id)
        if not webhook:
            raise KeyError("webhook not found")
        return self._deliver_once(
            webhook,
            _id(),
            "webhook.test",
            {"message": "WebNAS webhook test", "webhook_id": webhook_id},
            1,
        )

    def _subscribe_event(self, event: str) -> None:
        if event in self._unsubscribers:
            return

        def callback(payload: dict[str, Any], event_name: str = event) -> None:
            self.enqueue_event(event_name, payload)

        self._unsubscribers[event] = bus.subscribe(event, callback)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                return
            try:
                self._deliver_with_retries(*item)
            finally:
                self._queue.task_done()

    def startup(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            for event in event_types():
                self._subscribe_event(event)
            if self._event_listener_unsubscribe is None:
                self._event_listener_unsubscribe = on_event_registered(self._subscribe_event)
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="webnas-webhook-worker",
                daemon=True,
            )
            self._worker.start()

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=3)
        for unsubscribe in tuple(self._unsubscribers.values()):
            unsubscribe()
        self._unsubscribers.clear()
        if self._event_listener_unsubscribe:
            self._event_listener_unsubscribe()
            self._event_listener_unsubscribe = None


@lru_cache(maxsize=1)
def service() -> WebhookManagerService:
    return WebhookManagerService()


def startup() -> None:
    service().startup()


def shutdown() -> None:
    service().shutdown()
