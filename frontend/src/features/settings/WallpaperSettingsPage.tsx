import { Check, ImagePlus, Link2, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type SettingsMe, type SettingsPatch, type WallpaperItem } from "../../api";
import type { ToastFn, Translate } from "../../app/types";

const BUILT_IN_WALLPAPERS = [
  { id: "aurora", nameKey: "settings.wallpaperPreset.aurora", url: "/wallpapers/aurora.svg" },
  { id: "coast", nameKey: "settings.wallpaperPreset.coast", url: "/wallpapers/coast.svg" },
  { id: "dusk", nameKey: "settings.wallpaperPreset.dusk", url: "/wallpapers/dusk.svg" },
  { id: "graphite", nameKey: "settings.wallpaperPreset.graphite", url: "/wallpapers/graphite.svg" },
];

export function WallpaperSettingsPage({ settings, t, toast, onSave }: {
  settings: SettingsMe;
  t: Translate;
  toast: ToastFn;
  onSave: (patch: SettingsPatch) => Promise<void>;
}) {
  const [items, setItems] = useState<WallpaperItem[]>([]);
  const [selected, setSelected] = useState(settings.wallpaper);
  const [urlDraft, setUrlDraft] = useState(settings.wallpaper.startsWith("http") ? settings.wallpaper : "");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [maxFileSize, setMaxFileSize] = useState(10 * 1024 * 1024);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setSelected(settings.wallpaper); }, [settings.wallpaper]);
  useEffect(() => {
    let active = true;
    void api.wallpapers().then((value) => {
      if (!active) return;
      setItems(value.items);
      setMaxFileSize(value.max_file_size);
      setError("");
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : t("error.generic"));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [t]);

  async function choose(url: string) {
    const previous = selected;
    setSelected(url);
    try { await onSave({ wallpaper: url }); }
    catch (reason) { setSelected(previous); throw reason; }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type)) {
      toast(t("settings.wallpaperInvalidType"), "error");
      return;
    }
    if (file.size > maxFileSize) {
      toast(t("settings.wallpaperTooLarge").replace("{size}", formatBytes(maxFileSize)), "error");
      return;
    }
    setUploading(true); setError("");
    try {
      const item = await api.uploadWallpaper(file);
      setItems((current) => [item, ...current]);
      await choose(item.url);
      toast(t("settings.wallpaperUploaded"), "ok");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("error.generic");
      setError(message); toast(message, "error");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function remove(item: WallpaperItem) {
    try {
      if (selected === item.url) await choose("");
      await api.deleteWallpaper(item.id);
      setItems((current) => current.filter((entry) => entry.id !== item.id));
      toast(t("settings.wallpaperDeleted"), "ok");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("error.generic");
      setError(message); toast(message, "error");
    }
  }

  async function applyUrl() {
    const value = urlDraft.trim();
    if (!value) return;
    await choose(value);
  }

  const preview = selected || "/wallpapers/aurora.svg";
  return <div className="wallpaper-page">
    <section className="wallpaper-hero">
      <div className="wallpaper-monitor"><div style={{ backgroundImage: `url(${JSON.stringify(preview)})` }}><span>WebNAS</span></div><i /></div>
      <div><h3>{t("settings.wallpaperPreview")}</h3><p>{t("settings.wallpaperGalleryHint")}</p></div>
    </section>

    <section className="wallpaper-section">
      <header><div><h3>{t("settings.builtInWallpapers")}</h3><p>{t("settings.builtInWallpapersHint")}</p></div></header>
      <div className="wallpaper-gallery" role="radiogroup" aria-label={t("settings.builtInWallpapers")}>
        <WallpaperTile name={t("settings.noWallpaper")} url="" selected={!selected} onChoose={() => void choose("")} />
        {BUILT_IN_WALLPAPERS.map((item) => <WallpaperTile key={item.id} name={t(item.nameKey)} url={item.url} selected={selected === item.url} onChoose={() => void choose(item.url)} />)}
      </div>
    </section>

    <section className="wallpaper-section">
      <header>
        <div><h3>{t("settings.yourWallpapers")}</h3><p>{t("settings.yourWallpapersHint")}</p></div>
        <label className={`wallpaper-upload ${uploading ? "disabled" : ""}`}><Upload />{uploading ? t("status.loading") : t("settings.addWallpaper")}<input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" disabled={uploading} onChange={(event) => void upload(event.target.files?.[0])} /></label>
      </header>
      {error && <p className="error-state compact-error" role="alert">{error}</p>}
      {loading ? <div className="loading-state">{t("status.loading")}</div> : items.length ? <div className="wallpaper-gallery uploaded">{items.map((item) => <div className="wallpaper-owned" key={item.id}><WallpaperTile name={item.name} url={item.url} selected={selected === item.url} onChoose={() => void choose(item.url)} /><button type="button" title={t("action.delete")} aria-label={`${t("action.delete")}: ${item.name}`} onClick={() => void remove(item)}><Trash2 /></button></div>)}</div> : <div className="wallpaper-empty"><ImagePlus /><strong>{t("settings.noUploadedWallpapers")}</strong><span>{t("settings.noUploadedWallpapersHint")}</span></div>}
    </section>

    <section className="wallpaper-options">
      <label><span><strong>{t("settings.wallpaperFit")}</strong><small>{t("settings.wallpaperFitHint")}</small></span><select aria-label={t("settings.wallpaperFit")} value={settings.wallpaper_fit} onChange={(event) => void onSave({ wallpaper_fit: event.target.value as SettingsMe["wallpaper_fit"] })}>{["cover", "contain", "stretch", "center"].map((value) => <option key={value} value={value}>{t(`settings.fit.${value}`)}</option>)}</select></label>
      <div className="wallpaper-url-row"><span><Link2 /><span><strong>{t("settings.wallpaperUrl")}</strong><small>{t("settings.wallpaperUrlHint")}</small></span></span><div><input aria-label={t("settings.wallpaperUrl")} value={urlDraft} placeholder="https://…" onChange={(event) => setUrlDraft(event.target.value)} /><button className="button-primary" type="button" disabled={!urlDraft.trim()} onClick={() => void applyUrl()}>{t("action.apply")}</button></div></div>
    </section>
  </div>;
}

function WallpaperTile({ name, url, selected, onChoose }: { name: string; url: string; selected: boolean; onChoose: () => void }) {
  return <button className={`wallpaper-tile ${selected ? "selected" : ""} ${url ? "" : "none"}`} type="button" role="radio" aria-label={name} aria-checked={selected} onClick={onChoose}>
    <span style={url ? { backgroundImage: `url(${JSON.stringify(url)})` } : undefined}>{!url && <ImagePlus />}{selected && <i><Check /></i>}</span>
    <strong title={name}>{name}</strong>
  </button>;
}

function formatBytes(value: number) {
  return value >= 1024 * 1024 ? `${Math.round(value / (1024 * 1024))} MB` : `${Math.round(value / 1024)} KB`;
}
