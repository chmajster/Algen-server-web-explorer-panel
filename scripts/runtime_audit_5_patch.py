from pathlib import Path


def patch(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing fragment in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


patch(
    "backend/app/activity.py",
    '''def sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized = _sanitize(details or {})
    if not isinstance(sanitized, dict):
        return {}
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= _MAX_DETAILS_BYTES:
        return sanitized
    return {"truncated": True}


class ActivityRepository:''',
    '''def sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    sanitized = _sanitize(details or {})
    if not isinstance(sanitized, dict):
        return {}
    encoded = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= _MAX_DETAILS_BYTES:
        return sanitized
    return {"truncated": True}


def _activity_category(value: Any) -> ActivityCategory:
    try:
        return ActivityCategory(str(value))
    except (TypeError, ValueError):
        return ActivityCategory.module


def _activity_status(value: Any) -> ActivityStatus:
    try:
        return ActivityStatus(str(value))
    except (TypeError, ValueError):
        return ActivityStatus.info


class ActivityRepository:''',
)
patch("backend/app/activity.py", '            category=row["category"],', '            category=_activity_category(row["category"]),')
patch("backend/app/activity.py", '            status=row["status"],', '            status=_activity_status(row["status"]),')

patch(
    "backend/app/package_center/repository.py",
    '''from .models import PackageJobStatus, PackagePlan, PackageSourceInput


class PackageRepository:''',
    '''from .models import PackageJobStatus, PackagePlan, PackageSourceInput


def _json_value(value: Any, default: Any) -> Any:
    try:
        decoded = json.loads(value or json.dumps(default))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    if isinstance(default, dict):
        return decoded if isinstance(decoded, dict) else default
    if isinstance(default, list):
        return decoded if isinstance(decoded, list) else default
    return decoded


class PackageRepository:''',
)
patch(
    "backend/app/package_center/repository.py",
    '        result["plan"] = json.loads(result.pop("plan_json") or "{}")\n        result["warnings"] = json.loads(result.pop("warnings_json", "[]") or "[]")\n        result["result"] = json.loads(result.pop("result_json", "{}") or "{}")',
    '        result["plan"] = _json_value(result.pop("plan_json"), {})\n        result["warnings"] = _json_value(result.pop("warnings_json", "[]"), [])\n        result["result"] = _json_value(result.pop("result_json", "{}"), {})',
)
patch("backend/app/package_center/repository.py", '        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")', '        result["metadata"] = _json_value(result.pop("metadata_json"), {})')

patch(
    "backend/app/modules/ansible_controller/repository.py",
    '''def _json_object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


class ClosingConnection''',
    '''def _json_object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _json_list(value: Any) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


class ClosingConnection''',
)
patch(
    "backend/app/modules/ansible_controller/repository.py",
    '''        for column, target in JSON_COLUMNS.items():
            if column in result:
                try:
                    result[target] = json.loads(result.pop(column) or "{}")
                except (TypeError, ValueError):
                    result[target] = [] if column.endswith("ids_json") or column in {"tags_json", "skip_tags_json", "warnings_json"} else {}''',
    '''        list_columns = {"tags_json", "host_ids_json", "group_ids_json", "credential_ids_json", "skip_tags_json", "warnings_json"}
        for column, target in JSON_COLUMNS.items():
            if column in result:
                raw = result.pop(column)
                result[target] = _json_list(raw) if column in list_columns else _json_object(raw)''',
)
patch("backend/app/modules/ansible_controller/repository.py", '            result["tags"] = json.loads(result.pop("tags_json") or "[]")', '            result["tags"] = _json_list(result.pop("tags_json"))')

patch(
    "backend/app/modules/os_repositories/repository.py",
    '''SCHEMA_VERSION = 2


def object_id() -> str:''',
    '''SCHEMA_VERSION = 2
_JSON_LIST_FIELDS = {"architectures_json", "resolved_addresses_json", "rules_json", "warnings_json", "dependencies_json", "conflicts_json"}
_JSON_OBJECT_FIELDS = {"definition_json", "details_json", "value_json"}


def _decode_json_field(key: str, value: Any) -> Any:
    default: Any = [] if key in _JSON_LIST_FIELDS else {} if key in _JSON_OBJECT_FIELDS else None
    try:
        decoded = json.loads(value or json.dumps(default))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    if isinstance(default, list):
        return decoded if isinstance(decoded, list) else []
    if isinstance(default, dict):
        return decoded if isinstance(decoded, dict) else {}
    return decoded


def object_id() -> str:''',
)
patch("backend/app/modules/os_repositories/repository.py", '                result[key.removesuffix("_json")] = json.loads(result.pop(key) or "null")', '                result[key.removesuffix("_json")] = _decode_json_field(key, result.pop(key))')

activity = Path("backend/tests/test_activity.py")
text = activity.read_text(encoding="utf-8")
if "test_activity_corrupt_persisted_enums_do_not_break_listing" not in text:
    text = text.replace("import json\n", "import json\nimport sqlite3\n", 1)
    text += '''

def test_activity_corrupt_persisted_enums_do_not_break_listing(tmp_path: Path):
    repository = ActivityRepository(tmp_path / "activity-corrupt.sqlite3")
    event = repository.add(actor="alice", category=ActivityCategory.file, action="mkdir")
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE activity_events SET category=?, status=? WHERE id=?", ("future-category", "future-status", event.id))

    items, total = repository.list()
    assert total == 1
    assert items[0].category == ActivityCategory.module
    assert items[0].status == ActivityStatus.info
'''
    activity.write_text(text, encoding="utf-8")

package_tests = Path("backend/tests/test_package_center.py")
text = package_tests.read_text(encoding="utf-8")
if "test_package_repository_corrupt_persisted_json_isolated" not in text:
    text = text.replace("import os\n", "import os\nimport sqlite3\n", 1)
    text += '''

def test_package_repository_corrupt_persisted_json_isolated(tmp_path):
    repository = PackageRepository(tmp_path / "corrupt-package-center.sqlite3")
    created = repository.create_job(plan(), "alice")
    source = repository.create_source(PackageSourceInput(name="demo", github_url="https://github.com/example/demo"))
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE package_jobs SET plan_json=?, warnings_json=?, result_json=? WHERE id=?", ("[]", "{}", "{broken", created["id"]))
        connection.execute("UPDATE package_sources SET metadata_json=? WHERE id=?", ("[]", source["id"]))

    restored = repository.get_job(created["id"])
    assert restored is not None
    assert restored["plan"] == {}
    assert restored["warnings"] == []
    assert restored["result"] == {}
    assert restored["operation"] == restored["action"]
    assert repository.list_sources()[0]["metadata"] == {}
'''
    package_tests.write_text(text, encoding="utf-8")

resilience = Path("backend/tests/test_persisted_json_resilience.py")
text = resilience.read_text(encoding="utf-8")
if "test_ansible_wrong_shaped_json_fields_use_typed_defaults" not in text:
    text = text.replace("from __future__ import annotations\n", "from __future__ import annotations\n\nimport sqlite3\n", 1)
    text = text.replace("from app.modules.hosts_manager.models import HostInput\n", "from app.modules.hosts_manager.models import HostInput\nfrom app.modules.os_repositories.repository import RepositoryStore\n", 1)
    text += '''

def _row(sql: str):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(sql).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()


def test_ansible_wrong_shaped_json_fields_use_typed_defaults():
    decoded = AnsibleRepository._decode(_row("SELECT '{}' AS tags_json, '[]' AS config_json, 1 AS active"))
    assert decoded is not None
    assert decoded["tags"] == []
    assert decoded["config"] == {}


def test_os_repository_json_decoder_isolates_corrupt_and_wrong_shapes():
    decoded = RepositoryStore.row(_row("SELECT '{}' AS warnings_json, '[]' AS value_json, '{broken' AS details_json"))
    assert decoded is not None
    assert decoded["warnings"] == []
    assert decoded["value"] == {}
    assert decoded["details"] == {}
'''
    resilience.write_text(text, encoding="utf-8")

Path("CHANGELOG.d/runtime-audit-5.md").write_text('''# Runtime audit 5

## Fixed

- Activity Feed now tolerates unknown persisted `category` and `status` values instead of failing the whole activity listing when SQLite contains a stale or corrupted enum value.
- Package Center now safely decodes `plan_json`, `warnings_json`, `result_json`, and source `metadata_json`; malformed JSON and valid JSON with the wrong root type fall back to the expected object/list shape.
- Package Center no longer calls `.get()` on a non-object persisted plan.
- Ansible Controller now enforces the expected list/object shape for every persisted JSON column and safely decodes enrollment-token tags.
- OS Repositories now isolates malformed or wrong-shaped persisted JSON in repository, source, filter, sync-job, package, build, audit, and settings rows instead of propagating `JSONDecodeError` or an incompatible container type.

## Regression coverage

- Added Activity Feed coverage for corrupted persisted enum values.
- Added Package Center coverage for malformed and wrong-shaped job/source JSON.
- Added typed-shape regression coverage for Ansible Controller and OS Repositories persisted JSON decoders.
''', encoding="utf-8")
