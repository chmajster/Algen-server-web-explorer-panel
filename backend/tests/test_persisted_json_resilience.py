from __future__ import annotations

from app.app_store import state as app_state
from app.modules.ansible_controller.repository import AnsibleRepository
from app.modules.dcst.repository import DcstRepository
from app.modules.docker_manager.storage import DockerManagerStore
from app.modules.hosts_manager.batch_enrichment import HostRegistryService as BatchHostRegistryService
from app.modules.hosts_manager.models import HostInput
from app.plugins.models import StorePlugin
from app.plugins.repository import PluginRepository


def test_dcst_corrupt_state_and_audit_json_do_not_break_reads(tmp_path):
    repository = DcstRepository(tmp_path / "dcst.sqlite3")
    repository.set_state("sync", {"ok": True})
    repository.audit("admin", "sync", "service", "1", before={"ok": True}, after={"ok": True})
    with repository.connect() as connection:
        connection.execute("UPDATE dcst_state SET value_json='{' WHERE key='sync'")
        connection.execute("UPDATE dcst_audit SET before_json='{' ")
    assert repository.state("sync", {"fallback": True}) == {"fallback": True}
    assert repository.audits()[0]["before"] == {}


def test_docker_artifact_corrupt_metadata_isolated(tmp_path):
    store = DockerManagerStore(tmp_path / "docker")
    artifact = store.artifacts_dir / "artifact.txt"
    artifact.write_text("payload", encoding="utf-8")
    created = store.register_artifact(artifact, kind="diagnostic", display_name="Artifact", actor="admin", metadata={"ok": True})
    with store._connect() as connection:
        connection.execute("UPDATE artifacts SET metadata='{' WHERE id=?", (created["id"],))
    assert store.list_artifacts()[0]["metadata"] == {}


def test_ansible_corrupt_setting_falls_back_to_empty_object(tmp_path):
    repository = AnsibleRepository(tmp_path / "ansible" / "controller.sqlite3", tmp_path / "secrets" / "ansible.key")
    repository.save_setting("controller", {"forks": 5}, "admin")
    with repository.connect() as connection:
        connection.execute("UPDATE controller_settings SET config_json='{' WHERE key='controller'")
    assert repository.setting("controller") == {}


def test_hosts_manager_corrupt_settings_do_not_break_enrichment(tmp_path):
    repository = BatchHostRegistryService(
        tmp_path / "hosts" / "hosts.sqlite3",
        tmp_path / "secrets" / "hosts.key",
        tmp_path / "missing-controller.sqlite3",
    )
    host = repository.save_host(HostInput(name="node-01", address="192.168.50.10"), "admin")
    with repository.connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO hosts_manager_settings(key,value_json,updated_at,updated_by) VALUES('heartbeat_interval_seconds','{',1,'admin')"
        )
    assert repository._settings_value("heartbeat_interval_seconds", 30) == 30
    assert repository.list_hosts()[0]["id"] == host["id"]


def test_app_store_corrupt_or_non_object_state_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path)
    app_state.app_state_path("demo").write_text("{", encoding="utf-8")
    assert app_state.read_state("demo") == {"installed": False, "history": []}
    app_state.app_state_path("demo").write_text("[]", encoding="utf-8")
    assert app_state.read_state("demo") == {"installed": False, "history": []}


def test_plugin_corrupt_json_lists_do_not_break_repository(tmp_path):
    repository = PluginRepository(tmp_path / "plugins.sqlite3")
    repository.upsert(StorePlugin(id="demo-plugin", name="Demo", github_url="https://github.com/example/demo-plugin", capabilities=["filesystem.read"], permissions=["modules.view"]))
    with repository._connect() as connection:
        connection.execute("UPDATE plugins SET capabilities_json='{', permissions_json='{}' WHERE id='demo-plugin'")
    plugin = repository.get("demo-plugin")
    assert plugin is not None
    assert plugin.capabilities == []
    assert plugin.permissions == []
