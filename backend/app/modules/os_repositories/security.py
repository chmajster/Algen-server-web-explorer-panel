from __future__ import annotations

import ipaddress
import hashlib
import hmac
import os
import re
import socket
import subprocess
import secrets
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from ...package_center.executor import redact

SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
BACKUP_MAGIC = b"WORB1"


def encrypt_backup_payload(data: bytes, passphrase: str) -> bytes:
    if len(passphrase) < 12:
        raise ValueError("private-key backups require a passphrase of at least 12 characters")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(32)
    material = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=64, maxmem=128 * 1024 * 1024)
    encryption_key, mac_key = material[:32], material[32:]
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        stream.extend(hmac.new(encryption_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    ciphertext = bytes(left ^ right for left, right in zip(data, stream, strict=False))
    header = BACKUP_MAGIC + salt + nonce + ciphertext
    return header + hmac.new(mac_key, header, hashlib.sha256).digest()


def decrypt_backup_payload(data: bytes, passphrase: str) -> bytes:
    if len(data) < 85 or not data.startswith(BACKUP_MAGIC):
        raise ValueError("invalid encrypted private-key backup")
    salt, nonce, ciphertext, tag = data[5:21], data[21:53], data[53:-32], data[-32:]
    material = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=64, maxmem=128 * 1024 * 1024)
    header = data[:-32]
    if not hmac.compare_digest(tag, hmac.new(material[32:], header, hashlib.sha256).digest()):
        raise ValueError("private-key backup passphrase or authentication is invalid")
    stream = bytearray()
    counter = 0
    while len(stream) < len(ciphertext):
        stream.extend(hmac.new(material[:32], nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(left ^ right for left, right in zip(ciphertext, stream, strict=False))


def validate_mirror_url(url: str, *, allow_private_network: bool, allow_private_http: bool, resolver: Callable[..., list] = socket.getaddrinfo) -> list[str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("mirror URL must use HTTP(S) without credentials or fragments")
    if parsed.scheme == "http" and not allow_private_http:
        raise ValueError("HTTP mirrors require explicit approval")
    addresses: list[str] = []
    try:
        answers = resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError("mirror hostname could not be resolved") from error
    for answer in answers:
        address = str(answer[4][0]).split("%", 1)[0]
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved:
            raise ValueError("mirror resolves to a forbidden network address")
        if ip.is_private and not allow_private_network:
            raise ValueError("private mirrors require explicit private-network approval")
        addresses.append(str(ip))
    if not addresses:
        raise ValueError("mirror hostname did not resolve to an address")
    return sorted(set(addresses))


def managed_path(root: Path, value: str | Path) -> Path:
    target = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    base = root.resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes the managed repository directory")
    if target.is_symlink():
        raise ValueError("managed paths cannot be symlinks")
    return target


def run_tool(args: list[str], *, timeout: int = 300, cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if not args or not re.fullmatch(r"[A-Za-z0-9_./+-]+", args[0]):
        raise ValueError("invalid repository tool")
    result = subprocess.run(args, cwd=cwd, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, shell=False, env=SAFE_ENV)
    result.stdout = redact(result.stdout[-512 * 1024 :])
    result.stderr = redact(result.stderr[-512 * 1024 :])
    return result


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
