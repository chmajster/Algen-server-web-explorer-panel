from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from ...core.redaction import redact, redact_text, sensitive_key


class CredentialCipher:
    """Versioned credential envelope encryption with backward-compatible reads.

    New values use the WAC2 envelope backed by ChaCha20-Poly1305. Existing
    WAC1 values remain readable so installations can migrate without exposing
    plaintext credentials or rotating the master key in place.
    """

    VERSION = b"WAC2"
    LEGACY_VERSION = b"WAC1"
    NONCE_SIZE = 12
    TAG_SIZE = 16

    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self.key = self._load_or_create_key()
        self.aead_key = hmac.new(self.key, b"webnas-credentials/wac2-aead", hashlib.sha256).digest()
        self.legacy_enc_key = hmac.new(self.key, b"webnas-ansible/encryption", hashlib.sha256).digest()
        self.legacy_mac_key = hmac.new(self.key, b"webnas-ansible/authentication", hashlib.sha256).digest()

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

    @staticmethod
    def _aead_associated_data(associated_data: str) -> bytes:
        return CredentialCipher.VERSION + b"\0" + associated_data.encode("utf-8")

    def _legacy_stream(self, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self.legacy_enc_key,
                    nonce + counter.to_bytes(8, "big"),
                    hashlib.sha256,
                ).digest()
            )
            counter += 1
        return bytes(output[:length])

    def _encrypt_wac1(self, secret: str, *, associated_data: str = "") -> str:
        """Create a legacy envelope for migration/regression testing only."""
        raw = secret.encode("utf-8")
        nonce = secrets.token_bytes(32)
        ciphertext = bytes(
            left ^ right
            for left, right in zip(raw, self._legacy_stream(nonce, len(raw)), strict=True)
        )
        header = self.LEGACY_VERSION + nonce + associated_data.encode("utf-8") + b"\0" + ciphertext
        tag = hmac.new(self.legacy_mac_key, header, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(self.LEGACY_VERSION + nonce + tag + ciphertext).decode("ascii")

    def encrypt(self, secret: str, *, associated_data: str = "") -> str:
        nonce = secrets.token_bytes(self.NONCE_SIZE)
        ciphertext_and_tag = ChaCha20Poly1305(self.aead_key).encrypt(
            nonce,
            secret.encode("utf-8"),
            self._aead_associated_data(associated_data),
        )
        return base64.urlsafe_b64encode(self.VERSION + nonce + ciphertext_and_tag).decode("ascii")

    def _decrypt_wac1(self, raw: bytes, *, associated_data: str) -> str:
        if len(raw) < 68 or raw[:4] != self.LEGACY_VERSION:
            raise ValueError("invalid encrypted credential")
        nonce, tag, ciphertext = raw[4:36], raw[36:68], raw[68:]
        header = self.LEGACY_VERSION + nonce + associated_data.encode("utf-8") + b"\0" + ciphertext
        expected = hmac.new(self.legacy_mac_key, header, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("credential authentication failed")
        plaintext = bytes(
            left ^ right
            for left, right in zip(ciphertext, self._legacy_stream(nonce, len(ciphertext)), strict=True)
        )
        return plaintext.decode("utf-8")

    def decrypt(self, envelope: str, *, associated_data: str = "") -> str:
        try:
            raw = base64.urlsafe_b64decode(envelope.encode("ascii"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("invalid encrypted credential") from error

        if raw.startswith(self.VERSION):
            minimum = len(self.VERSION) + self.NONCE_SIZE + self.TAG_SIZE
            if len(raw) < minimum:
                raise ValueError("invalid encrypted credential")
            nonce = raw[4 : 4 + self.NONCE_SIZE]
            ciphertext_and_tag = raw[4 + self.NONCE_SIZE :]
            try:
                plaintext = ChaCha20Poly1305(self.aead_key).decrypt(
                    nonce,
                    ciphertext_and_tag,
                    self._aead_associated_data(associated_data),
                )
            except InvalidTag as error:
                raise ValueError("credential authentication failed") from error
            try:
                return plaintext.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("invalid encrypted credential") from error

        if raw.startswith(self.LEGACY_VERSION):
            return self._decrypt_wac1(raw, associated_data=associated_data)
        raise ValueError("invalid encrypted credential")

    def envelope_version(self, envelope: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(envelope.encode("ascii"))
        except (ValueError, UnicodeError) as error:
            raise ValueError("invalid encrypted credential") from error
        if raw.startswith(self.VERSION):
            return self.VERSION.decode("ascii")
        if raw.startswith(self.LEGACY_VERSION):
            return self.LEGACY_VERSION.decode("ascii")
        raise ValueError("invalid encrypted credential")

    def needs_migration(self, envelope: str) -> bool:
        return self.envelope_version(envelope) != self.VERSION.decode("ascii")

    def migrate(self, envelope: str, *, associated_data: str = "") -> str:
        plaintext = self.decrypt(envelope, associated_data=associated_data)
        if not self.needs_migration(envelope):
            return envelope
        return self.encrypt(plaintext, associated_data=associated_data)

    def export_encrypted(self, payload: dict[str, Any]) -> str:
        return self.encrypt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            associated_data="backup",
        )

    def import_encrypted(self, payload: str) -> dict[str, Any]:
        value = json.loads(self.decrypt(payload, associated_data="backup"))
        if not isinstance(value, dict):
            raise ValueError("invalid encrypted backup payload")
        return value


def atomic_private_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        mode,
    )
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
