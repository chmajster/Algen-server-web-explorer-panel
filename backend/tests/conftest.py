"""Small compatibility shims so policy tests can also be collected on Windows.

Production still requires Linux; individual tests monkeypatch these lookups with
the exact accounts and groups relevant to the behavior under test.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace


if sys.platform == "win32" or not os.environ.get("WEBNAS_CONFIG"):
    test_root = Path(tempfile.gettempdir()) / "webnas-pytest"
    test_root.mkdir(parents=True, exist_ok=True)
    config_path = test_root / "config.yaml"
    config_path.write_text(f"paths:\n  data_dir: '{(test_root / 'data').as_posix()}'\n  temp_dir: '{(test_root / 'tmp').as_posix()}'\n  log_dir: '{(test_root / 'logs').as_posix()}'\n", encoding="utf-8")
    os.environ["WEBNAS_CONFIG"] = str(config_path)


def _missing(value):
    raise KeyError(value)


try:
    import pwd  # noqa: F401
except ModuleNotFoundError:
    pwd_stub = ModuleType("pwd")
    pwd_stub.struct_passwd = tuple
    pwd_stub.getpwnam = _missing
    pwd_stub.getpwall = lambda: []
    pwd_stub.getpwuid = lambda uid: SimpleNamespace(pw_name=str(uid))
    sys.modules["pwd"] = pwd_stub

try:
    import grp  # noqa: F401
except ModuleNotFoundError:
    grp_stub = ModuleType("grp")
    grp_stub.struct_group = tuple
    grp_stub.getgrnam = _missing
    grp_stub.getgrgid = _missing
    grp_stub.getgrall = lambda: []
    sys.modules["grp"] = grp_stub
