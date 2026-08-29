from __future__ import annotations

import json
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from typing import Any

from ..core.redaction import redact, redact_text
from .models import SinkType


class DeliveryError(RuntimeError):
    pass


def safe_payload(alert: dict[str, Any]) -> dict[str, Any]:
    return redact(
        {
            "event": "webnas.alert",
            "id": alert.get("id", ""),
            "fingerprint": alert.get("fingerprint", ""),
            "state": alert.get("state", ""),
            "severity": alert.get("severity", ""),
            "source": alert.get("source", ""),
            "title": alert.get("title", ""),
            "object_ref": alert.get("object_ref", ""),
            "details": alert.get("details", {}),
            "first_seen_at": alert.get("first_seen_at"),
            "last_seen_at": alert.get("last_seen_at"),
        }
    )


def deliver(sink: dict[str, Any], alert: dict[str, Any]) -> None:
    sink_type = SinkType(str(sink["type"]))
    payload = safe_payload(alert)
    if sink_type in {SinkType.webhook, SinkType.ntfy}:
        _deliver_webhook(sink, payload, ntfy=sink_type == SinkType.ntfy)
        return
    if sink_type == SinkType.smtp:
        _deliver_smtp(sink, payload)
        return
    raise DeliveryError("unsupported notification sink")


def _deliver_webhook(sink: dict[str, Any], payload: dict[str, Any], *, ntfy: bool) -> None:
    url = str(sink.get("url", ""))
    if not url.startswith("https://"):
        raise DeliveryError("notification webhook must use HTTPS")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "WebNAS-AlertManager/1",
    }
    token = str(sink.get("token", ""))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ntfy:
        headers["Title"] = str(payload.get("title", "WebNAS alert"))[:256]
        headers["Priority"] = {
            "critical": "5",
            "error": "4",
            "warning": "3",
            "info": "2",
        }.get(str(payload.get("severity", "warning")), "3")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= int(response.status) < 300:
                raise DeliveryError(f"notification webhook returned HTTP {response.status}")
    except DeliveryError:
        raise
    except Exception as error:
        raise DeliveryError(redact_text(type(error).__name__)) from error


def _deliver_smtp(sink: dict[str, Any], payload: dict[str, Any]) -> None:
    message = EmailMessage()
    severity = str(payload.get("severity", "warning")).upper()
    state = str(payload.get("state", "firing")).upper()
    message["Subject"] = f"[WebNAS][{severity}][{state}] {payload.get('title', 'Alert')}"[:998]
    message["From"] = str(sink.get("smtp_from", ""))
    recipients = [str(item) for item in sink.get("smtp_to", []) if str(item)]
    if not recipients:
        raise DeliveryError("SMTP sink has no recipients")
    message["To"] = ", ".join(recipients)
    message.set_content(json.dumps(payload, ensure_ascii=False, indent=2))

    host = str(sink.get("smtp_host", ""))
    port = int(sink.get("smtp_port", 587))
    username = str(sink.get("smtp_username", ""))
    password = str(sink.get("smtp_password", ""))
    try:
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.ehlo()
            if bool(sink.get("smtp_starttls", True)):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(message)
    except Exception as error:
        raise DeliveryError(redact_text(type(error).__name__)) from error
