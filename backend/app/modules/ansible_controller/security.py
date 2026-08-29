from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from ...core.redaction import redact, redact_text, sensitive_key


class CredentialCipher:
    """Authenticated envelope encryption with a root-only key stored outside SQLite.

    The construction uses independent HMAC-SHA256 derived encryption and MAC
    keys, a random 256-bit nonce, a SHA256 counter keystream and encrypt-then-MAC.
    """

    VERSION = b"WAC1"

    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self.key = self._load_or_create_key()
        self.enc_key = hmac.new(self.key, b"webnas-ansible/encryption", hashlib.sha256).digest()
        self.mac_key = hmac.new(self.key, b"webnas-ansible/authentication", hashlib.sha256).digest()

    def _load_or_create_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.key_path.parent, 0o700)
        except OSError:
            pass
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if len(raw) != 32:
                raise RuntimeError("invalid ansible controller encryption key")
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return raw
        raw = secrets.token_bytes(32)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(self.key_path, flags, 0o600)
        try:
            os.write(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return raw

    def _stream(self, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(hmac.new(self.enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(output[:length])

    def encrypt(self, secret: str, *, associated_data: str = "") -> str:
        raw = secret.encode("utf-8")
        nonce = secrets.token_bytes(32)
        ciphertext = bytes(left ^ right for left, right in zip(raw, self._stream(nonce, len(raw)), strict=True))
        header = self.VERSION + nonce + associated_data.encode("utf-8") + b"\0" + ciphertext
        tag = hmac.new(self.mac_key, header, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(self.VERSION + nonce + tag + ciphertext).decode("ascii")

    def decrypt(self, envelope: str, *, associated_data: str = "") -> str:
        try:
            raw = base64.urlsafe_b64decode(envelope.encode("ascii"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("invalid encrypted credential") from error
        if len(raw) < 68 or raw[:4] != self.VERSION:
            raise ValueError("invalid encrypted credential")
        nonce, tag, ciphertext = raw[4:36], raw[36:68], raw[68:]
        header = self.VERSION + nonce + associated_data.encode("utf-8") + b"\0" + ciphertext
        expected = hmac.new(self.mac_key, header, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("credential authentication failed")
        plaintext = bytes(left ^ right for left, right in zip(ciphertext, self._stream(nonce, len(ciphertext)), strict=True))
        return plaintext.decode("utf-8")

    def export_encrypted(self, payload: dict[str, Any]) -> str:
        return self.encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), associated_data="backup")

    def import_encrypted(self, payload: str) -> dict[str, Any]:
        value = json.loads(self.decrypt(payload, associated_data="backup"))
        if not isinstance(value, dict):
            raise ValueError("invalid encrypted backup payload")
        return value


def atomic_private_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode)
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("private file write did not make progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, mode)


__all__ = [
    "CredentialCipher",
    "atomic_private_write",
    "redact",
    "redact_text",
    "sensitive_key",
]
