from __future__ import annotations

import json
from pathlib import Path

from app.config import AppConfig
from app.transport import TransportSettings, cookie_secure, read_transport_settings, render_nginx_transport, transport_state_path


def config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "server": {
                "port": 5000,
                "use_https": False,
                "tls_cert": "/etc/webnas/tls/webnas.crt",
                "tls_key": "/etc/webnas/tls/webnas.key",
            },
            "paths": {"data_dir": str(tmp_path)},
            "security": {"cookie_secure": False},
        }
    )


def test_http_is_effective_default(tmp_path: Path):
    cfg = config(tmp_path)
    settings = read_transport_settings(cfg)
    assert settings.use_https is False
    assert render_nginx_transport(settings, 5000) == "listen 5000;\n"
    assert cookie_secure(cfg) is False


def test_https_override_persists_and_secures_cookie(tmp_path: Path):
    cfg = config(tmp_path)
    path = transport_state_path(cfg)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "use_https": True,
                "tls_cert": "/etc/webnas/tls/webnas.crt",
                "tls_key": "/etc/webnas/tls/webnas.key",
            }
        ),
        encoding="utf-8",
    )
    settings = read_transport_settings(cfg)
    assert settings.use_https is True
    assert "listen 5000 ssl;" in render_nginx_transport(settings, 5000)
    assert cookie_secure(cfg) is True


def test_https_requires_certificate_paths():
    settings = TransportSettings(use_https=True)
    try:
        render_nginx_transport(settings, 5000)
    except ValueError as error:
        assert "certificate" in str(error).lower()
    else:
        raise AssertionError("HTTPS without certificate paths must fail")
