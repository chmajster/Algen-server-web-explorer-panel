import { useEffect, useRef, useState } from "react";
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
