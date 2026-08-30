from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .engine import PolicyEngine, PolicyExpressionError
from .models import POLICY_ID, PolicyDocument, PolicyFormat


class PolicyRepositoryError(RuntimeError):
    pass


class PolicyValidationError(PolicyRepositoryError):
    pass


class PolicyNotFoundError(PolicyRepositoryError):
    pass


class PolicyConflictError(PolicyRepositoryError):
    pass


@dataclass(slots=True)
class PolicyRecord:
    id: str
    format: PolicyFormat
    source: str
    document: PolicyDocument
    modified_at: float

    def to_dict(self, *, include_source: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "name": self.document.metadata.name,
            "description": self.document.metadata.description,
            "labels": self.document.metadata.labels,
            "enabled": self.document.spec.enabled,
            "rule_count": len(self.document.spec.rules),
            "format": self.format,
            "modified_at": self.modified_at,
            "valid": True,
            "error": None,
        }
        if include_source:
            value["source"] = self.source
        return value


class PolicyRepository:
    MAX_SOURCE_BYTES = 262_144

    def __init__(self, root: Path | None = None, *, engine: PolicyEngine | None = None):
        configured = os.environ.get("WEBNAS_POLICY_DIR")
        self.root = Path(root or configured or "/var/lib/webnas/policies")
        self.engine = engine or PolicyEngine()
        self._lock = threading.RLock()

    def parse(self, source: str, policy_format: PolicyFormat) -> PolicyDocument:
        if len(source.encode("utf-8")) > self.MAX_SOURCE_BYTES:
            raise PolicyValidationError("policy source exceeds 256 KiB")
        try:
            if policy_format == "json":
                value = json.loads(source)
            else:
                value = yaml.safe_load(source)
            if not isinstance(value, dict):
                raise PolicyValidationError("policy document must be an object")
            document = PolicyDocument.model_validate(value)
            self.engine.validate(document)
            return document
        except PolicyValidationError:
            raise
        except (json.JSONDecodeError, yaml.YAMLError, ValidationError, PolicyExpressionError, TypeError, ValueError) as exc:
            raise PolicyValidationError(str(exc)) from exc

    def validate_source(self, source: str, policy_format: PolicyFormat) -> dict[str, Any]:
        document = self.parse(source, policy_format)
        return {
            "valid": True,
            "id": document.metadata.name,
            "enabled": document.spec.enabled,
            "rule_count": len(document.spec.rules),
            "document": document.model_dump(mode="json", by_alias=True),
        }

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.root.exists():
                return []
            files = sorted([*self.root.glob("*.yaml"), *self.root.glob("*.json")], key=lambda item: item.name)
            items: list[dict[str, Any]] = []
            seen: set[str] = set()
            for path in files:
                if path.stem in seen:
                    items.append(self._invalid_item(path, "duplicate policy id exists in multiple formats"))
                    continue
                seen.add(path.stem)
                try:
                    items.append(self._read_path(path).to_dict())
                except PolicyRepositoryError as exc:
                    items.append(self._invalid_item(path, str(exc)))
            return items

    def summary(self) -> dict[str, Any]:
        items = self.list()
        valid = [item for item in items if item["valid"]]
        return {
            "total": len(items),
            "enabled": sum(bool(item["enabled"]) for item in valid),
            "disabled": sum(not bool(item["enabled"]) for item in valid),
            "invalid": sum(not bool(item["valid"]) for item in items),
            "rules": sum(int(item["rule_count"]) for item in valid),
            "formats": {
                "yaml": sum(item["format"] == "yaml" for item in items),
                "json": sum(item["format"] == "json" for item in items),
            },
        }

    def get(self, policy_id: str) -> PolicyRecord:
        self._validate_id(policy_id)
        with self._lock:
            path = self._existing_path(policy_id)
            if path is None:
                raise PolicyNotFoundError(f"policy not found: {policy_id}")
            return self._read_path(path)

    def save(self, source: str, policy_format: PolicyFormat, *, expected_id: str | None = None, create: bool = False) -> PolicyRecord:
        document = self.parse(source, policy_format)
        policy_id = document.metadata.name
        if expected_id is not None:
            self._validate_id(expected_id)
            if policy_id != expected_id:
                raise PolicyValidationError("metadata.name must match the policy id in the URL")
        with self._lock:
            existing = self._existing_path(policy_id)
            if create and existing is not None:
                raise PolicyConflictError(f"policy already exists: {policy_id}")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = self.root / f"{policy_id}.{policy_format}"
            rendered = self._render(document, policy_format)
            self._atomic_write(target, rendered)
            other = self.root / f"{policy_id}.{'json' if policy_format == 'yaml' else 'yaml'}"
            if other.exists() and other != target:
                other.unlink()
            return self._read_path(target)

    def delete(self, policy_id: str) -> None:
        self._validate_id(policy_id)
        with self._lock:
            path = self._existing_path(policy_id)
            if path is None:
                raise PolicyNotFoundError(f"policy not found: {policy_id}")
            path.unlink()

    def evaluate(self, policy_id: str, facts: dict[str, Any]) -> dict[str, Any]:
        return self.engine.evaluate(self.get(policy_id).document, facts)

    def evaluate_source(self, source: str, policy_format: PolicyFormat, facts: dict[str, Any]) -> dict[str, Any]:
        return self.engine.evaluate(self.parse(source, policy_format), facts)

    def evaluate_enabled(self, facts: dict[str, Any]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        invalid: list[dict[str, str]] = []
        with self._lock:
            if self.root.exists():
                for path in sorted([*self.root.glob("*.yaml"), *self.root.glob("*.json")], key=lambda item: item.name):
                    try:
                        record = self._read_path(path)
                        if record.document.spec.enabled:
                            results.append(self.engine.evaluate(record.document, facts))
                    except PolicyRepositoryError as exc:
                        invalid.append({"id": path.stem, "error": str(exc)})
        total_rules = sum(item["total"] for item in results)
        passed = sum(item["passed"] for item in results)
        failed = sum(item["failed"] for item in results)
        errors = sum(item["errors"] for item in results) + len(invalid)
        return {
            "scope": "enabled",
            "compliant": failed == 0 and errors == 0,
            "score": round((passed / total_rules) * 100) if total_rules else (100 if not invalid else 0),
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "total": total_rules,
            "policies": results,
            "invalid_policies": invalid,
        }

    def _read_path(self, path: Path) -> PolicyRecord:
        try:
            source = path.read_text(encoding="utf-8")
            policy_format: PolicyFormat = "json" if path.suffix == ".json" else "yaml"
            document = self.parse(source, policy_format)
            if document.metadata.name != path.stem:
                raise PolicyValidationError("metadata.name does not match the policy filename")
            return PolicyRecord(path.stem, policy_format, source, document, path.stat().st_mtime)
        except OSError as exc:
            raise PolicyRepositoryError(str(exc)) from exc

    def _existing_path(self, policy_id: str) -> Path | None:
        for suffix in ("yaml", "json"):
            path = self.root / f"{policy_id}.{suffix}"
            if path.exists():
                return path
        return None

    @staticmethod
    def _render(document: PolicyDocument, policy_format: PolicyFormat) -> str:
        value = document.model_dump(mode="json", by_alias=True)
        if policy_format == "json":
            return json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".policy-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_id(policy_id: str) -> None:
        if not POLICY_ID.fullmatch(policy_id):
            raise PolicyValidationError("policy id must use lowercase kebab-case")

    @staticmethod
    def _invalid_item(path: Path, error: str) -> dict[str, Any]:
        return {
            "id": path.stem,
            "name": path.stem,
            "description": "",
            "labels": {},
            "enabled": False,
            "rule_count": 0,
            "format": "json" if path.suffix == ".json" else "yaml",
            "modified_at": path.stat().st_mtime if path.exists() else 0,
            "valid": False,
            "error": error[:1000],
        }
