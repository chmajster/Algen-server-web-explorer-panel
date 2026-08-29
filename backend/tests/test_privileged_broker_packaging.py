from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_privileged_socket_is_group_restricted() -> None:
    unit = (ROOT / "packaging" / "webnas-privileged.socket").read_text(encoding="utf-8")
    assert "ListenStream=/run/webnas/privileged.sock" in unit
    assert "SocketUser=root" in unit
    assert "SocketGroup=webnas" in unit
    assert "SocketMode=0660" in unit
    assert "Accept=yes" not in unit


def test_privileged_service_is_the_explicit_root_boundary() -> None:
    unit = (ROOT / "packaging" / "webnas-privileged.service").read_text(encoding="utf-8")
    assert "User=root" in unit
    assert "Group=root" in unit
    assert "-m app.privileged_broker.server" in unit
    assert "ProtectKernelTunables=true" in unit
    assert "ProtectKernelModules=true" in unit
    assert "ProtectControlGroups=true" in unit
