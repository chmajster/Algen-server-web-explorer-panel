import asyncio
import stat
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from starlette.datastructures import UploadFile

from app import file_ops, write_policy


def test_ensure_temp_dir_uses_configured_tmpdir(monkeypatch, tmp_path: Path):
    configured = tmp_path / "webnas-tmp"
    monkeypatch.setattr(file_ops, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(temp_dir=str(configured))))

    result = file_ops.ensure_temp_dir()

    assert result == configured
    assert result.exists()


def test_classic_upload_staging_file_is_private_from_creation(monkeypatch, tmp_path: Path):
    staging = tmp_path / "tmp"
    destination = tmp_path / "home"
    destination.mkdir()
    monkeypatch.setattr(
        file_ops,
        "get_config",
        lambda: SimpleNamespace(
            paths=SimpleNamespace(temp_dir=str(staging)),
            security=SimpleNamespace(max_upload_size_mb=20),
        ),
    )
    monkeypatch.setattr(file_ops, "resolve_user_path", lambda _username, path: Path(path))
    monkeypatch.setattr(file_ops, "assert_path_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(write_policy, "assert_write_allowed", lambda _path: None)
    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: False)
    observed_modes: list[int] = []

    def import_upload(_username, operation, payload):
        assert operation == "import_upload"
        observed_modes.append(stat.S_IMODE(Path(payload["tmp"]).stat().st_mode))
        return {"ok": True}

    monkeypatch.setattr(file_ops, "run_user_op", import_upload)
    upload = UploadFile(filename="report.txt", file=BytesIO(b"private data"))

    result = asyncio.run(file_ops.save_upload("alice", str(destination), upload))

    assert result["size"] == len(b"private data")
    assert observed_modes == [0o600]
    assert not list(staging.glob("*.upload"))
