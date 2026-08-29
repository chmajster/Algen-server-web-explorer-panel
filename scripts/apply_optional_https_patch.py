#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


replace(
    "config.example.yaml",
    '''  # Standard installations terminate TLS at the stable nginx gateway. The
  # installer creates the private self-signed certificate below on first install
  # unless the administrator replaces these paths with an existing certificate.
  use_https: true
  tls_cert: "/etc/webnas/tls/webnas.crt"
  tls_key: "/etc/webnas/tls/webnas.key"
''',
    '''  # Standard installations start on HTTP. HTTPS can be enabled later from
  # Settings -> Administration without reinstalling WebNAS. Certificate paths
  # are kept ready so the release helper can bootstrap a local certificate.
  use_https: false
  tls_cert: "/etc/webnas/tls/webnas.crt"
  tls_key: "/etc/webnas/tls/webnas.key"
''',
)
replace("config.example.yaml", "  cookie_secure: true\n", "  cookie_secure: false\n")
replace(
    "config.example.yaml",
    '''  # Set this to true only when intentionally exposing the PAM-authenticated
  # panel over plaintext HTTP in an isolated lab. Existing pre-policy configs
  # without this key remain upgrade-compatible but are treated as legacy.
  allow_insecure_http: false
''',
    '''  # HTTP is the default transport for a fresh installation. Enable HTTPS in
  # Settings -> Administration when a protected transport is required.
  allow_insecure_http: true
''',
)

write(
    "backend/app/transport.py",
    '''from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, field_validator

from .config import AppConfig, get_config


TLS_PATH_RE = re.compile(r"^/[A-Za-z0-9._@:+/-]{1,4095}$")


class TransportSettings(BaseModel):
    use_https: bool = False
    tls_cert: str = ""
    tls_key: str = ""

    @field_validator("tls_cert", "tls_key")
    @classmethod
    def valid_tls_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not TLS_PATH_RE.fullmatch(value) or ".." in Path(value).parts:
            raise ValueError("TLS path must be an absolute path without whitespace or traversal")
        return value


def transport_state_path(cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    return Path(selected.paths.data_dir) / "settings" / "transport.json"


def transport_include_path(cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    return Path(selected.paths.data_dir) / "settings" / "nginx-transport.conf"


def default_transport(cfg: AppConfig | None = None) -> TransportSettings:
    selected = cfg or get_config()
    return TransportSettings(
        use_https=bool(selected.server.use_https),
        tls_cert=str(selected.server.tls_cert or ""),
        tls_key=str(selected.server.tls_key or ""),
    )


def read_transport_settings(cfg: AppConfig | None = None) -> TransportSettings:
    selected = cfg or get_config()
    defaults = default_transport(selected)
    path = transport_state_path(selected)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    try:
        return TransportSettings.model_validate({**defaults.model_dump(), **payload})
    except ValueError:
        return defaults


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def write_transport_settings(settings: TransportSettings, cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    path = transport_state_path(selected)
    _atomic_write(path, settings.model_dump_json(indent=2) + "\n", 0o600)
    return path


def render_nginx_transport(settings: TransportSettings, public_port: int) -> str:
    if public_port < 1 or public_port > 65535:
        raise ValueError("invalid public port")
    lines = [f"listen {public_port}{' ssl' if settings.use_https else ''};"]
    if settings.use_https:
        if not settings.tls_cert or not settings.tls_key:
            raise ValueError("TLS certificate and key paths are required when HTTPS is enabled")
        lines.extend(
            [
                f"ssl_certificate {settings.tls_cert};",
                f"ssl_certificate_key {settings.tls_key};",
            ]
        )
    return "\n".join(lines) + "\n"


def write_transport_include(settings: TransportSettings, public_port: int, cfg: AppConfig | None = None) -> Path:
    selected = cfg or get_config()
    path = transport_include_path(selected)
    _atomic_write(path, render_nginx_transport(settings, public_port), 0o640)
    return path


def cookie_secure(cfg: AppConfig | None = None) -> bool:
    selected = cfg or get_config()
    state_path = transport_state_path(selected)
    if state_path.exists():
        return read_transport_settings(selected).use_https
    return bool(selected.security.cookie_secure or selected.server.use_https)
''',
)

write(
    "backend/app/transport_settings.py",
    '''from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from .audit import logger
from .config import get_config
from .privileged_broker.runtime import broker_required, systemd_action
from .rbac import authorize
from .security import SessionUser, get_session_user, require_csrf
from .transport import (
    TransportSettings,
    read_transport_settings,
    render_nginx_transport,
    transport_include_path,
    transport_state_path,
    write_transport_include,
    write_transport_settings,
)


router = APIRouter()


def _current_user(request: Request) -> SessionUser:
    user = get_session_user(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, user)
    return user


def _active_backend_port() -> int:
    cfg = get_config()
    path = Path(cfg.paths.data_dir) / "settings" / "deployment.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        port = int(payload.get("active_port") or 0) if isinstance(payload, dict) else 0
    except (OSError, ValueError, json.JSONDecodeError):
        port = 0
    if port < 1 or port > 65535:
        raise HTTPException(409, "HTTPS settings require the standard nginx blue/green installation")
    return port


def _nginx_base_config(backend_port: int) -> str:
    cfg = get_config()
    include_path = transport_include_path(cfg)
    return f"""server {{
    include {include_path};
    client_max_body_size 0;
    location / {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""


def _reload_nginx(actor: str) -> subprocess.CompletedProcess[str]:
    if broker_required():
        return systemd_action("reload", "nginx.service", actor=actor)
    return subprocess.run(
        ["systemctl", "reload", "nginx.service"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _payload(settings: TransportSettings) -> dict[str, object]:
    cfg = get_config()
    return {
        **settings.model_dump(),
        "scheme": "https" if settings.use_https else "http",
        "public_port": cfg.server.port,
    }


@router.get("/api/settings/transport")
def get_transport_settings(user: SessionUser = Depends(_current_user)):
    authorize(user, "system.status")
    return _payload(read_transport_settings())


@router.put("/api/settings/transport")
def save_transport_settings(payload: TransportSettings, request: Request, user: SessionUser = Depends(_current_user)):
    authorize(user, "system.restart")
    cfg = get_config()
    backend_port = _active_backend_port()
    state_path = transport_state_path(cfg)
    include_path = transport_include_path(cfg)
    previous_state = state_path.read_bytes() if state_path.exists() else None
    previous_include = include_path.read_bytes() if include_path.exists() else None

    try:
        # Validate before replacing any durable files.
        render_nginx_transport(payload, cfg.server.port)
        write_transport_settings(payload, cfg)
        write_transport_include(payload, cfg.server.port, cfg)
        result = _reload_nginx(f"transport-{user.username}")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "nginx reload failed")
    except Exception as error:
        if previous_state is None:
            state_path.unlink(missing_ok=True)
        else:
            state_path.write_bytes(previous_state)
        if previous_include is None:
            include_path.unlink(missing_ok=True)
        else:
            include_path.write_bytes(previous_include)
        try:
            _reload_nginx(f"transport-rollback-{user.username}")
        except Exception:
            pass
        raise HTTPException(400, f"Could not apply transport settings: {error}") from error

    logger.info(
        "transport_settings_updated actor=%s https=%s cert=%s",
        user.username,
        payload.use_https,
        payload.tls_cert,
    )
    return _payload(payload)
''',
)

replace(
    "backend/app/modules/builtin/settings/manifest.yaml",
    "routers: [app.settings:router, app.resource_processes:router]\n",
    "routers: [app.settings:router, app.resource_processes:router, app.transport_settings:router]\n",
)

replace(
    "backend/app/security.py",
    "from .sqlite_utils import ClosingConnection\n",
    "from .sqlite_utils import ClosingConnection\nfrom .transport import cookie_secure as transport_cookie_secure\n",
)
replace(
    "backend/app/security.py",
    "        secure=cfg.security.cookie_secure,\n",
    "        secure=transport_cookie_secure(cfg),\n",
)
replace(
    "backend/app/security.py",
    "        secure=cfg.security.cookie_secure,\n",
    "        secure=transport_cookie_secure(cfg),\n",
)

replace(
    "scripts/webnas_release.py",
    "from app.core.redaction import redact_text  # noqa: E402\n",
    "from app.core.redaction import redact_text  # noqa: E402\nfrom app.transport import TransportSettings, render_nginx_transport  # noqa: E402\n",
)

replace(
    "scripts/webnas_release.py",
    '''    def ensure_tls_certificate(self) -> None:
        if config_value(self.config, "server", "use_https", "false").lower() != "true":
            return
        raw_cert = config_value(self.config, "server", "tls_cert")
        raw_key = config_value(self.config, "server", "tls_key")
        if not raw_cert or not raw_key:
            raise RuntimeError("TLS is enabled but server.tls_cert or server.tls_key is not configured")
''',
    '''    def transport_settings(self) -> TransportSettings:
        defaults = TransportSettings(
            use_https=config_value(self.config, "server", "use_https", "false").lower() == "true",
            tls_cert=config_value(self.config, "server", "tls_cert"),
            tls_key=config_value(self.config, "server", "tls_key"),
        )
        data_dir = Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas"))
        state_path = data_dir / "settings" / "transport.json"
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return defaults
        if not isinstance(payload, dict):
            return defaults
        try:
            return TransportSettings.model_validate({**defaults.model_dump(), **payload})
        except ValueError:
            return defaults

    def transport_include_path(self) -> Path:
        data_dir = Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas"))
        return data_dir / "settings" / "nginx-transport.conf"

    def write_transport_include(self) -> None:
        path = self.transport_include_path()
        settings = self.transport_settings()
        atomic_write(path, render_nginx_transport(settings, self.public_port), 0o640)
        try:
            shutil.chown(path.parent, user=self.service_user, group=self.service_user)
            shutil.chown(path, user=self.service_user, group=self.service_user)
        except (LookupError, OSError):
            pass

    def ensure_tls_certificate(self) -> None:
        transport = self.transport_settings()
        raw_cert = transport.tls_cert
        raw_key = transport.tls_key
        if not raw_cert or not raw_key:
            if transport.use_https:
                raise RuntimeError("TLS is enabled but server.tls_cert or server.tls_key is not configured")
            return
''',
)

replace(
    "scripts/webnas_release.py",
    '''    def nginx(self, port: int) -> str:
        use_https = config_value(self.config, "server", "use_https", "false").lower() == "true"
        tls_cert = config_value(self.config, "server", "tls_cert")
        tls_key = config_value(self.config, "server", "tls_key")
        insecure_policy = config_value(self.config, "security", "allow_insecure_http", "legacy").lower()
        if not use_https and insecure_policy == "false":
            raise RuntimeError(
                "Refusing public plaintext HTTP because security.allow_insecure_http=false; "
                "enable TLS or explicitly opt in only for an isolated lab"
            )
        if not use_https and insecure_policy not in {"true", "false"}:
            print(
                "WebNAS security warning: legacy configuration still publishes plaintext HTTP. "
                "Enable TLS or set security.allow_insecure_http=true explicitly only for an isolated lab.",
                file=sys.stderr,
            )
        listen = f"listen {self.public_port}{' ssl' if use_https else ''};"
        tls = ""
        if use_https:
            if not tls_cert or not tls_key or not Path(tls_cert).is_file() or not Path(tls_key).is_file():
                raise RuntimeError("TLS is enabled but its certificate or key is unavailable")
            tls = f"\\n    ssl_certificate {tls_cert};\\n    ssl_certificate_key {tls_key};"
        return f"""server {{
    {listen}{tls}
    client_max_body_size 0;
''',
    '''    def nginx(self, port: int) -> str:
        include_path = self.transport_include_path()
        return f"""server {{
    include {include_path};
    client_max_body_size 0;
''',
)

replace(
    "scripts/webnas_release.py",
    '''    def activate_nginx(self, port: int) -> None:
        candidate = self.nginx_config.with_suffix(".candidate")
''',
    '''    def activate_nginx(self, port: int) -> None:
        self.write_transport_include()
        candidate = self.nginx_config.with_suffix(".candidate")
''',
)
replace(
    "scripts/webnas_release.py",
    '''    def public_health(self, attempts: int = 20) -> None:
        use_https = config_value(self.config, "server", "use_https", "false").lower() == "true"
        scheme = "https" if use_https else "http"
        context = ssl._create_unverified_context() if use_https else None  # noqa: S323 - validates local handover only.
''',
    '''    def public_health(self, attempts: int = 20) -> None:
        use_https = self.transport_settings().use_https
        scheme = "https" if use_https else "http"
        context = ssl._create_unverified_context() if use_https else None  # noqa: S323 - validates local handover only.
''',
)

replace(
    "frontend/src/modules/settings/api/client.ts",
    '''import type { SettingsMe, SettingsPatch, WallpaperItem } from "../../../core/api/contracts";

export const settingsClient = {
''',
    '''import type { SettingsMe, SettingsPatch, WallpaperItem } from "../../../core/api/contracts";

export type TransportSettings = {
  use_https: boolean;
  tls_cert: string;
  tls_key: string;
  scheme: "http" | "https";
  public_port: number;
};

export const settingsClient = {
''',
)
replace(
    "frontend/src/modules/settings/api/client.ts",
    '''  deleteWallpaper: (wallpaperId: string) => request<{ ok: boolean }>(`/api/settings/wallpapers/${encodeURIComponent(wallpaperId)}`, { method: "DELETE", body: "{}" }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) })
''',
    '''  deleteWallpaper: (wallpaperId: string) => request<{ ok: boolean }>(`/api/settings/wallpapers/${encodeURIComponent(wallpaperId)}`, { method: "DELETE", body: "{}" }),
  transportSettings: () => request<TransportSettings>("/api/settings/transport"),
  saveTransportSettings: (payload: Pick<TransportSettings, "use_https" | "tls_cert" | "tls_key">) => request<TransportSettings>("/api/settings/transport", { method: "PUT", body: JSON.stringify(payload) }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) })
''',
)

write(
    "frontend/src/features/settings/HttpsSettingsControl.tsx",
    '''import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LockKeyhole } from "lucide-react";
import { settingsClient, type TransportSettings } from "../../modules/settings/api/client";
import type { ToastFn } from "../../app/types";


type Props = {
  active: boolean;
  locale: string;
  toast: ToastFn;
};

const copy = {
  pl: {
    title: "HTTPS",
    description: "HTTP jest domyślnym trybem WebNAS. HTTPS można włączyć na tym samym porcie bez reinstalacji.",
    enabled: "Włącz HTTPS",
    enabledHint: "Po zapisaniu nginx przełączy publiczny port na TLS i przeglądarka otworzy adres HTTPS.",
    cert: "Certyfikat TLS",
    key: "Klucz prywatny TLS",
    pathsHint: "Podaj bezwzględne ścieżki na serwerze. Domyślna instalacja przygotowuje lokalny certyfikat w /etc/webnas/tls/.",
    save: "Zapisz transport",
    saving: "Zapisywanie…",
    current: "Aktualny protokół",
    loadError: "Nie udało się odczytać ustawień HTTPS.",
    saved: "Ustawienia transportu zostały zastosowane.",
  },
  en: {
    title: "HTTPS",
    description: "HTTP is the default WebNAS transport. HTTPS can be enabled on the same port without reinstalling.",
    enabled: "Enable HTTPS",
    enabledHint: "After saving, nginx switches the public port to TLS and the browser opens the HTTPS address.",
    cert: "TLS certificate",
    key: "TLS private key",
    pathsHint: "Use absolute server paths. The default installation prepares a local certificate under /etc/webnas/tls/.",
    save: "Save transport",
    saving: "Saving…",
    current: "Current protocol",
    loadError: "Could not load HTTPS settings.",
    saved: "Transport settings were applied.",
  },
} as const;

export function HttpsSettingsControl({ active, locale, toast }: Props) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [settings, setSettings] = useState<TransportSettings | null>(null);
  const [draft, setDraft] = useState<Pick<TransportSettings, "use_https" | "tls_cert" | "tls_key"> | null>(null);
  const [saving, setSaving] = useState(false);
  const text = locale.toLowerCase().startsWith("pl") ? copy.pl : copy.en;

  useEffect(() => {
    if (!active) { setTarget(null); return; }
    const root = anchorRef.current?.parentElement;
    const resolve = () => setTarget(root?.querySelector(".settings-content") || null);
    resolve();
    if (!root) return;
    const observer = new MutationObserver(resolve);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [active]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void settingsClient.transportSettings().then((value) => {
      if (cancelled) return;
      setSettings(value);
      setDraft({ use_https: value.use_https, tls_cert: value.tls_cert, tls_key: value.tls_key });
    }).catch(() => {
      if (!cancelled) toast(text.loadError, "error", "admin");
    });
    return () => { cancelled = true; };
  }, [active, text.loadError, toast]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const updated = await settingsClient.saveTransportSettings(draft);
      setSettings(updated);
      setDraft({ use_https: updated.use_https, tls_cert: updated.tls_cert, tls_key: updated.tls_key });
      toast(text.saved, "ok", "admin");
      const desiredProtocol = updated.use_https ? "https:" : "http:";
      if (window.location.protocol !== desiredProtocol) {
        const next = new URL(window.location.href);
        next.protocol = desiredProtocol;
        window.location.assign(next.toString());
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : text.loadError, "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  const card = active && target && draft ? createPortal(
    <div className="settings-card-stack" data-testid="https-settings-card">
      <section className="settings-card">
        <h3><LockKeyhole size={18} /> {text.title}</h3>
        <p>{text.description}</p>
        <div className="setting-row">
          <div><strong>{text.enabled}</strong><small>{text.enabledHint}</small></div>
          <div className="setting-control"><label className="settings-switch"><input type="checkbox" aria-label={text.enabled} checked={draft.use_https} onChange={(event) => setDraft({ ...draft, use_https: event.target.checked })} /><span aria-hidden="true" /></label></div>
        </div>
        <div className="setting-row">
          <div><strong>{text.cert}</strong><small>{text.pathsHint}</small></div>
          <div className="setting-control"><input type="text" value={draft.tls_cert} onChange={(event) => setDraft({ ...draft, tls_cert: event.target.value })} /></div>
        </div>
        <div className="setting-row">
          <div><strong>{text.key}</strong></div>
          <div className="setting-control"><input type="text" value={draft.tls_key} onChange={(event) => setDraft({ ...draft, tls_key: event.target.value })} /></div>
        </div>
        <div className="setting-row">
          <div><strong>{text.current}</strong></div>
          <div className="setting-control"><code>{settings?.scheme || (draft.use_https ? "https" : "http")}://:{settings?.public_port || window.location.port}</code></div>
        </div>
        <div className="settings-actions"><button className="button-primary" type="button" disabled={saving || (draft.use_https && (!draft.tls_cert || !draft.tls_key))} onClick={() => void save()}>{saving ? text.saving : text.save}</button></div>
      </section>
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
''',
)

replace(
    "frontend/src/modules/settings/manifest.tsx",
    '''import type { PolicySubject } from "../../features/admin/IdentityApp";

const SettingsApp = lazy''',
    '''import type { PolicySubject } from "../../features/admin/IdentityApp";
import { HttpsSettingsControl } from "../../features/settings/HttpsSettingsControl";

const SettingsApp = lazy''',
)
replace(
    "frontend/src/modules/settings/manifest.tsx",
    '''      <SettingsApp settings={context.profile} initialSection={initialSection} initialPolicySubject={policySubject(context.item.moduleId)} deepLink={context.item.deepLink} t={context.t} toast={context.toast} onSettingsChange={context.onSettingsChange} onOpenApp={context.openApp} onDeepLinkClose={context.clearDeepLink} onSectionChange={context.setInitialPath} />
      <UpdateDetailsPolicyControl active={initialSection === "policies"} t={context.t} toast={context.toast} />
''',
    '''      <SettingsApp settings={context.profile} initialSection={initialSection} initialPolicySubject={policySubject(context.item.moduleId)} deepLink={context.item.deepLink} t={context.t} toast={context.toast} onSettingsChange={context.onSettingsChange} onOpenApp={context.openApp} onDeepLinkClose={context.clearDeepLink} onSectionChange={context.setInitialPath} />
      <HttpsSettingsControl active={initialSection === "administration"} locale={context.profile.language} toast={context.toast} />
      <UpdateDetailsPolicyControl active={initialSection === "policies"} t={context.t} toast={context.toast} />
''',
)

replace(
    "backend/tests/test_release_deployment.py",
    '''def test_new_transport_policy_refuses_public_plaintext_http(tmp_path: Path):
    target = deployment(tmp_path)
    target.config.write_text(
        "server:\\n  use_https: false\\nsecurity:\\n  allow_insecure_http: false\\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Refusing public plaintext HTTP"):
        target.nginx(target.new_port)


def test_explicit_lab_transport_policy_allows_plaintext_http(tmp_path: Path):
    target = deployment(tmp_path)
    target.config.write_text(
        "server:\\n  use_https: false\\nsecurity:\\n  allow_insecure_http: true\\n",
        encoding="utf-8",
    )

    nginx = target.nginx(target.new_port)

    assert "listen 5000;" in nginx
    assert "listen 5000 ssl;" not in nginx


def test_tls_gateway_requires_and_uses_configured_certificate(tmp_path: Path):
''',
    '''def test_plaintext_gateway_is_supported_by_default(tmp_path: Path):
    target = deployment(tmp_path)
    target.config.write_text(
        "server:\\n  use_https: false\\nsecurity:\\n  allow_insecure_http: false\\n",
        encoding="utf-8",
    )

    settings = target.transport_settings()
    directives = release_module.render_nginx_transport(settings, target.public_port)

    assert settings.use_https is False
    assert "listen 5000;" in directives
    assert " ssl" not in directives


def test_transport_override_can_enable_https(tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "webnas.crt"
    key = tmp_path / "webnas.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    state = tmp_path / "data" / "settings" / "transport.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"use_https": True, "tls_cert": str(cert), "tls_key": str(key)}), encoding="utf-8")

    settings = target.transport_settings()
    directives = release_module.render_nginx_transport(settings, target.public_port)

    assert settings.use_https is True
    assert "listen 5000 ssl;" in directives
    assert f"ssl_certificate {cert};" in directives


def test_tls_gateway_requires_and_uses_configured_certificate(tmp_path: Path):
''',
)
replace(
    "backend/tests/test_release_deployment.py",
    '''    nginx = target.nginx(target.new_port)

    assert "listen 5000 ssl;" in nginx
    assert f"ssl_certificate {cert};" in nginx
    assert f"ssl_certificate_key {key};" in nginx
''',
    '''    settings = target.transport_settings()
    nginx = release_module.render_nginx_transport(settings, target.public_port)

    assert "listen 5000 ssl;" in nginx
    assert f"ssl_certificate {cert};" in nginx
    assert f"ssl_certificate_key {key};" in nginx
''',
)

write(
    "backend/tests/test_transport.py",
    '''from __future__ import annotations

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
    assert render_nginx_transport(settings, 5000) == "listen 5000;\\n"
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
''',
)

write(
    "CHANGELOG.d/optional-https-settings.md",
    '''- Fresh standard installations now use HTTP by default instead of requiring HTTPS.
- Added Administration settings for enabling/disabling HTTPS and configuring TLS certificate/key paths without reinstalling WebNAS.
- The nginx blue/green gateway persists the selected transport mode across application updates.
''',
)

# The workflow and this helper are implementation scaffolding only; keep them out of the PR diff.
Path("scripts/apply_optional_https_patch.py").unlink(missing_ok=True)
Path(".github/workflows/optional-https-patch.yml").unlink(missing_ok=True)
