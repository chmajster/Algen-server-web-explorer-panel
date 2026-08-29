from __future__ import annotations

from app.core.redaction import redact, redact_text
from app.modules.ansible_controller import security as ansible_security


def test_redact_text_removes_common_secret_forms():
    private_key = "-----BEGIN PRIVATE KEY-----\nvery-secret-key\n-----END PRIVATE KEY-----"
    raw = "\n".join(
        [
            "password=correct-horse-battery-staple",
            "Authorization: Bearer abc.def.ghi",
            "api_key = key-123456",
            "database_url=postgresql://alice:db-password@example.test/app",
            private_key,
        ]
    )

    safe = redact_text(raw)

    for secret in (
        "correct-horse-battery-staple",
        "abc.def.ghi",
        "key-123456",
        "db-password",
        "very-secret-key",
    ):
        assert secret not in safe
    assert "password=[REDACTED]" in safe
    assert "Bearer [REDACTED]" in safe
    assert "postgresql://alice:[REDACTED]@example.test/app" in safe
    assert "[REDACTED PRIVATE KEY]" in safe


def test_redact_uses_key_names_and_known_secret_values():
    payload = {
        "username": "alice",
        "api_token": "token-value",
        "nested": {
            "safe": "prefix raw-secret suffix",
            "private_key": "key-value",
        },
    }

    safe = redact(payload, known_secrets=["raw-secret"])

    assert safe == {
        "username": "alice",
        "api_token": "[REDACTED]",
        "nested": {
            "safe": "prefix [REDACTED] suffix",
            "private_key": "[REDACTED]",
        },
    }


def test_redaction_bounds_text_and_nested_structures():
    assert redact_text("x" * 100, limit=12).endswith("\n[TRUNCATED]")

    value: object = "leaf"
    for _ in range(8):
        value = {"safe": value}

    safe = redact(value)
    current = safe
    for _ in range(7):
        if current == "[TRUNCATED]":
            break
        current = current["safe"]
    assert current == "[TRUNCATED]"


def test_ansible_security_keeps_compatibility_exports():
    assert ansible_security.redact_text is redact_text
    assert ansible_security.redact is redact
