from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_runtime_audit_5_uses_typed_persisted_decoders():
    package_repository = source("package_center/repository.py")
    ansible_repository = source("modules/ansible_controller/repository.py")
    os_repository = source("modules/os_repositories/repository.py")
    activity = source("activity.py")

    assert '_json_value(result.pop("plan_json"), {})' in package_repository
    assert '_json_value(result.pop("warnings_json", "[]"), [])' in package_repository
    assert '_json_value(result.pop("metadata_json"), {})' in package_repository
    assert 'result["tags"] = _json_list(result.pop("tags_json"))' in ansible_repository
    assert '_decode_json_field(key, result.pop(key))' in os_repository
    assert 'category=_activity_category(row["category"])' in activity
    assert 'status=_activity_status(row["status"])' in activity
