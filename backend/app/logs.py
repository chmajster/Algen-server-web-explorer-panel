"""Compatibility facade for the historical ``app.logs`` module.

Log models, parsers, filters, source adapters, persistence and HTTP routing are
implemented in ``app.log_system``. Re-exports below keep existing imports and
monkeypatch-based regression tests compatible during the staged migration.
"""
from __future__ import annotations

import shutil
import subprocess

from . import log_system as _log_system
from .activity import record_activity
from .config import get_config
from .identity.permissions import authorize, has_permission
from .log_system import adapters as _adapters
from .log_system import api as _api
from .log_system import files as _files
from .log_system import filtering as _filtering
from .log_system import parsing as _parsing
from .log_system import service as _service
from .log_system import sources as _sources
from .log_system import storage as _storage
from .log_system.execution import run_bounded as _run_bounded

_SUBPROCESS_MODULE = subprocess

router = _api.router
parse_journal_boots = _api.parse_journal_boots
infer_effective_priority = _log_system.models.infer_effective_priority
parse_journal_record = _parsing.parse_journal_record
parse_dmesg_record = _parsing.parse_dmesg_record
group_traceback_entries = _parsing.group_traceback_entries
safe_fields = _parsing.safe_fields
_validate_regex = _filtering.validate_regex
_decode_cursor = _filtering.decode_cursor
_encode_cursor = _filtering.encode_cursor
_matches = _filtering.matches
_authorize_source = _sources.authorize_source
_journal_entries = _sources.journal_entries
_dmesg_entries = _sources.dmesg_entries
_source_known = _sources.source_known
MAX_REGEX_LENGTH = _log_system.models.MAX_REGEX_LENGTH
HOST_RE = _log_system.models.HOST_RE
LogEntry = _log_system.models.LogEntry
SavedView = _log_system.models.SavedView
SavedViewPayload = _log_system.models.SavedViewPayload
ExportRequest = _log_system.models.ExportRequest


def _available_files():
    return _files.available_files()


def _read_tail(path, max_lines):
    return _files.read_tail(path, max_lines)


def _file_entries(source, limit):
    return _files.file_entries(source, limit, available=_available_files)


def _views_path(username):
    _storage.get_config = get_config
    return _storage.views_path(username)


def _read_views(username):
    _storage.get_config = get_config
    return _storage.read_views(username)


def _write_views(username, views):
    _storage.get_config = get_config
    return _storage.write_views(username, views)


def _sync_service_hooks() -> None:
    _service._authorize_source = _authorize_source
    _service._source_known = _source_known
    _service.has_permission = has_permission
    _adapters.journal_reader = _journal_entries
    _adapters.file_reader = _file_entries
    _adapters.dmesg_reader = _dmesg_entries


def query_entries(user, **kwargs):
    _sync_service_hooks()
    return _service.query_entries(user, **kwargs)


def log_boots(user):
    _api.authorize = authorize
    _api.run_bounded = _run_bounded
    _api.shutil = shutil
    return _api.log_boots(user)


def log_export(payload, user):
    _api.authorize = authorize
    _api.query_entries = query_entries
    _api.record_activity = record_activity
    return _api.log_export(payload, user)
