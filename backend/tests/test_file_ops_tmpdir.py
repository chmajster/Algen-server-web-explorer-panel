from pathlib import Path
from types import SimpleNamespace

from app import file_ops


def test_ensure_temp_dir_uses_configured_tmpdir(monkeypatch, tmp_path: Path):
    configured = tmp_path / "webnas-tmp"
    monkeypatch.setattr(file_ops, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(temp_dir=str(configured))))

    result = file_ops.ensure_temp_dir()

    assert result == configured
    assert result.exists()
