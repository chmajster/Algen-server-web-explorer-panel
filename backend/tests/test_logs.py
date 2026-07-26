import gzip
import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import logs
from app.identity.models import Role
from app.identity.permissions import Permission, ROLE_PERMISSIONS
from app.security import SessionUser


USER = SessionUser(username="alice", csrf_token="csrf")


def test_journal_json_is_normalized_bounded_and_redacted():
    record = {
        "__CURSOR": "cursor-1",
        "__REALTIME_TIMESTAMP": "1720000000123456",
        "PRIORITY": "3",
        "MESSAGE": "request failed authorization=Bearer-secret",
        "_SYSTEMD_UNIT": "webnas.service",
        "SYSLOG_IDENTIFIER": "python",
        "_HOSTNAME": "nas",
        "_PID": "1234",
        "_UID": "1000",
        "PASSWORD": "never-return-this",
    }

    parsed = logs.parse_journal_record(record)

    assert parsed is not None
    assert parsed.cursor == "cursor-1"
    assert parsed.severity == "error"
    assert parsed.unit == "webnas.service"
    assert parsed.pid == 1234
    assert parsed.uid == 1000
    assert "Bearer-secret" not in parsed.message
    assert parsed.fields["PASSWORD"] == "[REDACTED]"


def test_journal_parser_isolates_malformed_and_binary_records():
    assert logs.parse_journal_record("not-json") is None
    parsed = logs.parse_journal_record({"MESSAGE": [104, 101, 108, 108, 111, 255], "PRIORITY": "7"})
    assert parsed is not None
    assert parsed.message.startswith("hello")
    assert parsed.severity == "debug"


@pytest.mark.parametrize("pattern", ["(a+)+", ".*+", "a" * (logs.MAX_REGEX_LENGTH + 1), "["])
def test_regex_validation_rejects_expensive_or_invalid_patterns(pattern):
    with pytest.raises(HTTPException) as caught:
        logs._validate_regex(pattern)
    assert caught.value.status_code == 400


def test_combined_filters_are_applied_on_the_backend(monkeypatch):
    entries = [
        logs.LogEntry(id="1", source="journal", priority=3, severity="error", unit="webnas.service", message="Disk FAILED"),
        logs.LogEntry(id="2", source="journal", priority=6, severity="info", unit="webnas.service", message="Disk ready"),
        logs.LogEntry(id="3", source="journal", priority=3, severity="error", unit="ssh.service", message="Login failed"),
    ]
    monkeypatch.setattr(logs, "_authorize_source", lambda user, source: None)
    monkeypatch.setattr(logs, "_journal_entries", lambda *args, **kwargs: entries)

    result = logs.query_entries(
        USER,
        source="journal",
        query='"disk" failed',
        case_sensitive=False,
        priority=[3],
        unit="webnas.service",
        limit=20,
    )

    assert [item["id"] for item in result["items"]] == ["1"]


def test_sensitive_journal_records_require_security_permission(monkeypatch):
    entries = [
        logs.LogEntry(id="safe", source="journal", identifier="systemd", message="Service started"),
        logs.LogEntry(id="secret", source="journal", identifier="sshd", message="Authentication details"),
    ]
    monkeypatch.setattr(logs, "_authorize_source", lambda user, source: None)
    monkeypatch.setattr(logs, "_journal_entries", lambda *args, **kwargs: entries)
    monkeypatch.setattr(logs, "has_permission", lambda username, permission: False)

    result = logs.query_entries(USER, source="journal", limit=20)

    assert [item["id"] for item in result["items"]] == ["safe"]


def test_unit_container_time_and_cursor_validation(monkeypatch):
    monkeypatch.setattr(logs, "_authorize_source", lambda user, source: None)
    with pytest.raises(HTTPException):
        logs._journal_entries("journal", limit=1, priority=[], unit="../../bad", pid=None, uid=None, identifier="", transport="", hostname="", device="", username="", group="", boot_id="", since=None, until=None, continuation={}, direction="older")
    with pytest.raises(HTTPException):
        logs.query_entries(USER, source="container:../../bad", limit=10)
    with pytest.raises(HTTPException):
        logs.query_entries(USER, source="journal", since=20, until=10, limit=10)
    with pytest.raises(HTTPException):
        logs._decode_cursor("not-base64", "journal")


def test_file_tail_does_not_require_reading_the_whole_file(tmp_path):
    path = tmp_path / "large.log"
    path.write_bytes(b"x" * (3 * 1024 * 1024) + b"\nlast-one\nlast-two\n")

    assert logs._read_tail(path, 2) == ["last-one", "last-two"]


def test_compressed_rotated_file_is_bounded_and_readable(tmp_path):
    path = tmp_path / "syslog.1.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("old\nnew\n")

    assert logs._read_tail(path, 1) == ["new"]


def test_arbitrary_file_source_is_never_accepted(monkeypatch):
    monkeypatch.setattr(logs, "_available_files", lambda: {})
    with pytest.raises(HTTPException) as caught:
        logs._file_entries("file:../../etc/shadow", 20)
    assert caught.value.status_code == 404


def test_non_journal_cursor_advances_over_filtered_results(monkeypatch):
    entries = [
        logs.LogEntry(
            id=str(index),
            timestamp=f"2026-01-01T00:00:0{index}Z",
            severity="info",
            priority=6,
            source="file:syslog",
            message=f"{'match' if index % 2 == 0 else 'skip'}-{index}",
        )
        for index in range(6)
    ]
    monkeypatch.setattr(logs, "_source_known", lambda source: True)
    monkeypatch.setattr(logs, "_authorize_source", lambda user, source: None)
    monkeypatch.setattr(logs, "_file_entries", lambda source, limit: entries[:limit])
    monkeypatch.setattr(logs, "has_permission", lambda username, permission: True)

    first = logs.query_entries(USER, source="file:syslog", query="match", limit=2)
    second = logs.query_entries(USER, source="file:syslog", query="match", limit=2, cursor=first["next_cursor"])

    assert [item["id"] for item in first["items"]] == ["0", "2"]
    assert [item["id"] for item in second["items"]] == ["4"]


def test_command_timeout_is_converted_to_safe_api_error(monkeypatch):
    class Process:
        stdout = io.BytesIO()
        stderr = io.BytesIO()
        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("journalctl", timeout)
            return -9
        def kill(self):
            return None
    monkeypatch.setattr(logs.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(HTTPException) as caught:
        logs._run_bounded(["journalctl"])
    assert caught.value.status_code == 504
    assert "journalctl" not in str(caught.value.detail)


def test_saved_views_are_private_atomic_and_validated(monkeypatch, tmp_path):
    monkeypatch.setattr(logs, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path))))
    view = logs.SavedView(id="a" * 32, name="Errors", source="journal", filters={"priority": [3]})

    logs._write_views("alice", [view])

    assert logs._read_views("alice") == [view]
    assert logs._read_views("bob") == []
    assert not logs._views_path("alice").with_suffix(".tmp").exists()
    with pytest.raises(ValueError):
        logs.SavedViewPayload(name="unsafe", source="../../etc/shadow")


def test_log_permissions_follow_requested_role_policy():
    assert Permission.LOGS_VIEW_SECURITY.value in ROLE_PERMISSIONS[Role.admin]
    assert Permission.LOGS_VIEW_SYSTEM.value in ROLE_PERMISSIONS[Role.operator]
    assert Permission.LOGS_VIEW_SECURITY.value not in ROLE_PERMISSIONS[Role.operator]
    assert Permission.LOGS_EXPORT.value in ROLE_PERMISSIONS[Role.auditor]
    assert Permission.LOGS_VIEW_SYSTEM.value not in ROLE_PERMISSIONS[Role.user]
    assert Permission.LOGS_VIEW_OWN.value in ROLE_PERMISSIONS[Role.user]


def test_single_character_hostname_is_valid():
    assert logs.HOST_RE.fullmatch("a")
    assert logs.HOST_RE.fullmatch("nas-01.local")
    assert not logs.HOST_RE.fullmatch("-nas")


def test_export_is_utf8_and_reports_truncation(monkeypatch):
    monkeypatch.setattr(logs, "authorize", lambda user, permission: None)
    monkeypatch.setattr(logs, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(logs, "query_entries", lambda *args, **kwargs: {
        "items": [{"timestamp": "2026-01-01T00:00:00Z", "severity": "info", "source": "journal", "unit": "webnas.service", "identifier": "python", "pid": 1, "uid": 0, "hostname": "nas", "message": "Zażółć"}],
        "has_more": True,
    })

    response = logs.log_export(logs.ExportRequest(format="csv"), USER)

    assert "Zażółć".encode() in response.body
    assert response.headers["x-webnas-truncated"] == "true"
    assert "webnas-logs-journal-" in response.headers["content-disposition"]


BOOT_ID = "a" * 32


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (json.dumps([{"boot_id": BOOT_ID, "index": -1}, "ignored", 4]), 1),
        (json.dumps({"boot-id": BOOT_ID, "index": 0}), 1),
        (f'{{"bootId":"{BOOT_ID}","index":-2}}\n{{"boot_id":"{"b" * 32}"}}', 2),
        (f'["bad",{{"boot_id":"{BOOT_ID}"}}]\n', 1),
        ("", 0),
        ("not-json\n[]\n42", 0),
        (json.dumps([{"boot_id": [], "index": {}, "first": [], "last": None}, {}]), 0),
    ],
)
def test_journal_boot_json_parser_accepts_supported_shapes(stdout, expected):
    assert len(logs.parse_journal_boots(stdout)) == expected


def test_journal_boot_parser_normalizes_fields_without_type_assumptions():
    parsed = logs.parse_journal_boots(json.dumps({
        "bootId": BOOT_ID,
        "index": "bad",
        "first_entry": "1000000",
        "last": 3000000,
    }))

    assert parsed == [{
        "id": BOOT_ID,
        "index": 0,
        "first": "1000000",
        "last": 3000000,
        "duration_seconds": 2.0,
        "current": True,
    }]


def test_log_boots_falls_back_to_text_and_hides_command_error(monkeypatch):
    calls = iter([
        (1, "", "unsupported --output"),
        (0, f"-1 {BOOT_ID} Mon 2026-01-01 00:00:00 UTC — Tue 2026-01-02 00:00:00 UTC", ""),
    ])
    monkeypatch.setattr(logs, "authorize", lambda *args: None)
    monkeypatch.setattr(logs.shutil, "which", lambda name: "/usr/bin/journalctl")
    monkeypatch.setattr(logs, "_run_bounded", lambda *args, **kwargs: next(calls))

    response = logs.log_boots(USER)

    assert response["status"] == "available"
    assert response["items"][0]["id"] == BOOT_ID


def test_log_boots_handles_missing_program_and_nonzero_fallback(monkeypatch):
    monkeypatch.setattr(logs, "authorize", lambda *args: None)
    monkeypatch.setattr(logs.shutil, "which", lambda name: None)
    assert logs.log_boots(USER) == {"items": [], "status": "missing_program"}

    monkeypatch.setattr(logs.shutil, "which", lambda name: "/usr/bin/journalctl")
    monkeypatch.setattr(logs, "_run_bounded", lambda *args, **kwargs: (2, "", "private traceback"))
    response = logs.log_boots(USER)
    assert response["status"] == "error"
    assert "traceback" not in response["error"]


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Traceback (most recent call last):", "python_traceback"),
        ("AttributeError: list has no get", "python_exception"),
        ("SomeCustomError: failed", "python_exception"),
        ("ERROR request failed", "error_signal"),
        ("FATAL: cannot continue", "error_signal"),
        ("Segmentation fault (core dumped)", "error_signal"),
    ],
)
def test_effective_priority_detects_real_errors(message, reason):
    assert logs.infer_effective_priority(message, 6, {}) == (3, reason)


@pytest.mark.parametrize(
    "message",
    [
        "0 errors",
        "no errors",
        "no errors detected",
        "error count: 0",
        "error rate: 0",
        "without error",
        "ignore_errors",
        "error handling enabled",
        "documentation about error handling",
    ],
)
def test_effective_priority_avoids_benign_error_phrases(message):
    assert logs.infer_effective_priority(message, 6, {}) == (6, None)


def test_effective_priority_never_weakens_source_priority():
    assert logs.infer_effective_priority("AttributeError: failed", 2, {}) == (2, None)


def _trace_entry(identifier, second, message, *, pid=10, unit="webnas.service", secret=""):
    return logs.LogEntry(
        id=identifier,
        timestamp=f"2026-01-01T00:00:0{second}+00:00",
        source="journal",
        unit=unit,
        pid=pid,
        priority=6,
        message=f"{message}{secret}",
        fields={"_BOOT_ID": BOOT_ID},
    )


def test_traceback_records_are_grouped_and_redacted():
    entries = [
        _trace_entry("1", 0, "Traceback (most recent call last):"),
        _trace_entry("2", 1, '  File "/app/main.py", line 4, in run'),
        _trace_entry("3", 1, "    value.get()", secret=" password=very-secret"),
        _trace_entry("4", 2, "AttributeError: list has no get"),
    ]

    grouped = logs.group_traceback_entries(entries)

    assert len(grouped) == 1
    assert grouped[0].priority == 3
    assert grouped[0].severity_reason == "python_traceback"
    assert grouped[0].fields["merged_count"] == 4
    assert "very-secret" not in grouped[0].message
    assert "\n  File " in grouped[0].message


@pytest.mark.parametrize(
    "replacement",
    [
        _trace_entry("2", 1, '  File "/app/main.py", line 4', pid=11),
        _trace_entry("2", 1, '  File "/app/main.py", line 4', unit="other.service"),
        _trace_entry("2", 3, '  File "/app/main.py", line 4'),
    ],
)
def test_traceback_group_stops_at_context_or_time_boundary(replacement):
    entries = [
        _trace_entry("1", 0, "Traceback (most recent call last):"),
        replacement,
        _trace_entry("3", 1, "AttributeError: failed"),
    ]
    assert len(logs.group_traceback_entries(entries)) == 3


def test_independent_tracebacks_are_not_merged_together():
    first = [
        _trace_entry("1", 0, "Traceback (most recent call last):"),
        _trace_entry("2", 0, "ValueError: first"),
    ]
    second = [
        _trace_entry("3", 1, "Traceback (most recent call last):"),
        _trace_entry("4", 1, "TypeError: second"),
    ]
    assert len(logs.group_traceback_entries(first + second)) == 2


def test_unmergeable_traceback_lines_are_still_marked_as_errors():
    entries = [
        logs.LogEntry(id="1", source="file:syslog", priority=6, message="Traceback (most recent call last):"),
        logs.LogEntry(id="2", source="file:syslog", priority=6, message='  File "/app/main.py", line 4'),
        logs.LogEntry(id="3", source="file:syslog", priority=6, message="ValueError: failed"),
    ]

    marked = logs.group_traceback_entries(entries)

    assert len(marked) == 3
    assert all(item.priority == 3 and item.severity_reason == "python_traceback" for item in marked)


def test_exports_include_effective_and_original_levels(monkeypatch):
    item = logs.LogEntry(
        id="trace",
        source="journal",
        priority=6,
        message="AttributeError: failed",
    ).model_dump(mode="json")
    monkeypatch.setattr(logs, "authorize", lambda *args: None)
    monkeypatch.setattr(logs, "record_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(logs, "query_entries", lambda *args, **kwargs: {"items": [item], "has_more": False})

    csv_response = logs.log_export(logs.ExportRequest(format="csv"), USER)
    txt_response = logs.log_export(logs.ExportRequest(format="txt"), USER)
    json_response = logs.log_export(logs.ExportRequest(format="json"), USER)
    jsonl_response = logs.log_export(logs.ExportRequest(format="jsonl"), USER)

    assert b"priority,severity,original_priority,original_severity" in csv_response.body
    assert b"ERROR priority=3; original=info/6; inferred=python_exception" in txt_response.body
    assert json.loads(json_response.body)["items"][0]["original_priority"] == 6
    assert json.loads(jsonl_response.body)["original_severity"] == "info"
