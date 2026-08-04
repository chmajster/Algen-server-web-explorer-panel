from __future__ import annotations

from types import SimpleNamespace

from app import update_detail_policy


def _config(tmp_path):
    return SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path)))


def test_update_detail_policy_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(update_detail_policy, "get_config", lambda: _config(tmp_path))

    value = update_detail_policy._read_policy()

    assert value["policy_id"] == "updates.detailed_steps"
    assert value["detailed_steps"] is False
    assert value["default_detailed_steps"] is False


def test_update_detail_policy_persists_enabled_value(tmp_path, monkeypatch):
    monkeypatch.setattr(update_detail_policy, "get_config", lambda: _config(tmp_path))

    saved = update_detail_policy._write_policy(
        update_detail_policy.UpdateDetailPolicy(detailed_steps=True)
    )
    loaded = update_detail_policy._read_policy()

    assert saved["detailed_steps"] is True
    assert loaded["detailed_steps"] is True
    assert (tmp_path / "settings" / "update_detail_policy.json").stat().st_mode & 0o777 == 0o600


def test_invalid_policy_file_falls_back_to_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(update_detail_policy, "get_config", lambda: _config(tmp_path))
    path = tmp_path / "settings" / "update_detail_policy.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"detailed_steps":"yes"}', encoding="utf-8")

    assert update_detail_policy._read_policy()["detailed_steps"] is False


def test_default_public_payload_contains_only_disabled_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(update_detail_policy, "get_config", lambda: _config(tmp_path))

    value = update_detail_policy.get_public_update_detail_policy(SimpleNamespace())

    assert value == {"detailed_steps": False}
