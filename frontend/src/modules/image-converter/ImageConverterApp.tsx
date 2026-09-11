import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { AlertTriangle, CheckCircle2, Download, FileImage, FolderOpen, Gauge, Images, Info, SlidersHorizontal, Upload, WandSparkles, XCircle } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { imageConverterClient } from "./api/client";
import type { ConversionResult, DirectoryBrowser, ImageConverterLimits, ImageFormat } from "./api/client";
import "./image-converter.css";

type InputMode = "server" | "upload";
type OverwritePolicy = "rename" | "skip" | "overwrite";
type Preset = "balanced" | "web" | "high";

const DEFAULT_LIMITS: ImageConverterLimits = {
  max_upload_files: 100,
  max_directory_files: 500,
  max_file_bytes: 50 * 1024 * 1024,
  max_batch_bytes: 500 * 1024 * 1024,
  max_pixels: 100_000_000,
  max_dimension: 32_768,
};
const SUPPORTED_INPUT_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "heic", "heif", "avif"]);

function formatBytes(value: number) {
  const negative = value < 0;
  const absolute = Math.abs(value);
  const formatted = absolute < 1024 ? `${absolute} B` : absolute < 1024 * 1024 ? `${(absolute / 1024).toFixed(1)} KB` : `${(absolute / (1024 * 1024)).toFixed(1)} MB`;
  return negative ? `-${formatted}` : formatted;
}

function fileIdentity(file: File) {
  const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return `${relativePath || file.name}:${file.size}:${file.lastModified}`;
}

function isSupportedInput(file: File) {
  const extension = file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() ?? "" : "";
  return SUPPORTED_INPUT_EXTENSIONS.has(extension);
}

function triggerDownload(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "converted-images.zip";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function ImageConverterApp({ homePath, permissions, language, toast }: { homePath: string; permissions: readonly string[]; language: string; toast: ToastFn }) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    title: pl ? "Konwerter obrazów" : "Image Converter",
    subtitle: pl ? "Konwertuj, skaluj i optymalizuj zdjęcia bez opuszczania WebNAS." : "Convert, resize and optimize images without leaving WebNAS.",
    source: pl ? "Źródło" : "Source",
    settings: pl ? "Ustawienia konwersji" : "Conversion settings",
    result: pl ? "Wynik" : "Result",
    server: pl ? "Katalog na serwerze" : "Server directory",
    upload: pl ? "Pliki z komputera" : "Files from computer",
    current: pl ? "Wybrany katalog" : "Selected directory",
    output: pl ? "Katalog wynikowy" : "Output directory",
    outputHint: pl ? "Puste pole utworzy podkatalog converted-FORMAT w wybranym katalogu." : "Leave empty to create a converted-FORMAT subdirectory inside the selected directory.",
    recursive: pl ? "Uwzględnij podkatalogi" : "Include subdirectories",
    images: pl ? "Obrazy" : "Images",
    emptyDirectory: pl ? "W tym katalogu nie ma obsługiwanych obrazów." : "No supported images in this directory.",
    chooseFiles: pl ? "Wybierz zdjęcia" : "Choose images",
    chooseLocalDirectory: pl ? "Wybierz cały katalog" : "Choose folder",
    dropTitle: pl ? "Upuść zdjęcia tutaj" : "Drop images here",
    drop: pl ? "lub wybierz pojedyncze pliki albo cały katalog z komputera" : "or choose individual files or a whole folder from your computer",
    selected: pl ? "Wybrane pliki" : "Selected files",
    clear: pl ? "Wyczyść" : "Clear",
    remove: pl ? "Usuń plik" : "Remove file",
    format: pl ? "Format wynikowy" : "Output format",
    quality: pl ? "Jakość" : "Quality",
    resize: pl ? "Zmiana rozmiaru" : "Resize",
    width: pl ? "Szerokość" : "Width",
    height: pl ? "Wysokość" : "Height",
    originalSize: pl ? "bez zmian" : "unchanged",
    keepAspect: pl ? "Zachowaj proporcje" : "Keep aspect ratio",
    stripMetadata: pl ? "Usuń metadane EXIF/ICC" : "Strip EXIF/ICC metadata",
    prefix: pl ? "Prefiks" : "Prefix",
    suffix: pl ? "Sufiks" : "Suffix",
    collision: pl ? "Gdy plik istnieje" : "If output exists",
    rename: pl ? "Utwórz nową nazwę" : "Create unique name",
    skip: pl ? "Pomiń" : "Skip",
    overwrite: pl ? "Nadpisz" : "Overwrite",
    presets: pl ? "Preset" : "Preset",
    balanced: pl ? "Zbalansowany" : "Balanced",
    web: pl ? "WWW / mały plik" : "Web / small file",
    high: pl ? "Wysoka jakość" : "High quality",
    advanced: pl ? "Opcje zaawansowane" : "Advanced options",
    convert: pl ? "Rozpocznij konwersję" : "Start conversion",
    converting: pl ? "Konwertowanie…" : "Converting…",
    converted: pl ? "Przekonwertowano" : "Converted",
    failed: pl ? "Błędy" : "Failed",
    skipped: pl ? "Pominięto" : "Skipped",
    download: pl ? "Pobierz ZIP" : "Download ZIP",
    sourceSize: pl ? "Rozmiar wejściowy" : "Input size",
    outputSize: pl ? "Rozmiar wynikowy" : "Output size",
    saved: pl ? "Oszczędność" : "Saved",
    noPermission: pl ? "Nie masz uprawnienia do konwersji obrazów." : "You do not have permission to convert images.",
    folderUp: pl ? "Katalog wyżej" : "Parent directory",
    truncated: pl ? "Lista została ograniczona do pierwszych 1000 pozycji." : "The list was limited to the first 1000 entries.",
    loading: pl ? "Wczytywanie…" : "Loading…",
    ready: pl ? "Gotowe do konwersji" : "Ready to convert",
    chooseSource: pl ? "Wybierz źródło, aby rozpocząć" : "Choose a source to begin",
    details: pl ? "Szczegóły plików" : "File details",
    failuresDetails: pl ? "Szczegóły błędów" : "Failure details",
  };

  const canConvert = permissions.includes("image_converter.convert");
  const [mode, setMode] = useState<InputMode>("server");
  const [formats, setFormats] = useState<ImageFormat[]>([]);
  const [limits, setLimits] = useState<ImageConverterLimits>(DEFAULT_LIMITS);
  const [format, setFormat] = useState("webp");
  const [quality, setQuality] = useState(90);
  const [browser, setBrowser] = useState<DirectoryBrowser | null>(null);
  const [sourceDirectory, setSourceDirectory] = useState(homePath);
  const [outputDirectory, setOutputDirectory] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [result, setResult] = useState<ConversionResult | null>(null);
  const [width, setWidth] = useState(0);
  const [height, setHeight] = useState(0);
  const [keepAspect, setKeepAspect] = useState(true);
  const [stripMetadata, setStripMetadata] = useState(true);
  const [prefix, setPrefix] = useState("");
  const [suffix, setSuffix] = useState("");
  const [overwritePolicy, setOverwritePolicy] = useState<OverwritePolicy>("rename");
  const directoryInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    directoryInput.current?.setAttribute("webkitdirectory", "");
    void imageConverterClient.formats().then(({ formats: available, limits: serverLimits }) => {
      setFormats(available);
      if (serverLimits) setLimits(serverLimits);
      if (available.length) setFormat((current) => available.some((item) => item.id === current) ? current : available[0].id);
    }).catch((error) => toast(String(error), "error"));
  }, [toast]);

  const loadDirectory = useCallback(async (path: string) => {
    setBusy(true);
    try {
      const next = await imageConverterClient.browse(path);
      setBrowser(next);
      setSourceDirectory(next.path);
      setResult(null);
    } catch (error) {
      toast(String(error), "error");
    } finally {
      setBusy(false);
    }
  }, [toast]);

  useEffect(() => { void loadDirectory(homePath); }, [homePath, loadDirectory]);

  function appendFiles(next: File[]) {
    const seen = new Set(files.map(fileIdentity));
    const merged = [...files];
    let totalBytes = merged.reduce((sum, file) => sum + file.size, 0);
    let unsupported = 0;
    let oversized = 0;
    let limited = 0;

    for (const file of next) {
      const key = fileIdentity(file);
      if (seen.has(key)) continue;
      if (!isSupportedInput(file)) {
        unsupported += 1;
        continue;
      }
      if (file.size > limits.max_file_bytes) {
        oversized += 1;
        continue;
      }
      if (merged.length >= limits.max_upload_files || totalBytes + file.size > limits.max_batch_bytes) {
        limited += 1;
        continue;
      }
      seen.add(key);
      merged.push(file);
      totalBytes += file.size;
    }

    setFiles(merged);
    setResult(null);

    const rejected: string[] = [];
    if (unsupported) rejected.push(pl ? `${unsupported} pominięto: nieobsługiwany format` : `${unsupported} skipped: unsupported format`);
    if (oversized) rejected.push(pl ? `${oversized} pominięto: plik przekracza ${formatBytes(limits.max_file_bytes)}` : `${oversized} skipped: file exceeds ${formatBytes(limits.max_file_bytes)}`);
    if (limited) rejected.push(pl ? `${limited} pominięto: przekroczono limit paczki` : `${limited} skipped: batch limit exceeded`);
    if (rejected.length) toast(rejected.join(" · "), "error");
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    appendFiles(Array.from(event.dataTransfer.files));
  }

  function removeFile(index: number) {
    setFiles((current) => current.filter((_file, currentIndex) => currentIndex !== index));
    setResult(null);
  }

  function applyPreset(preset: Preset) {
    if (preset === "web") { setFormat("webp"); setQuality(75); setWidth(1920); setHeight(1920); setKeepAspect(true); setStripMetadata(true); }
    if (preset === "balanced") { setFormat("webp"); setQuality(85); setWidth(0); setHeight(0); setKeepAspect(true); setStripMetadata(true); }
    if (preset === "high") { setFormat("jpeg"); setQuality(95); setWidth(0); setHeight(0); setKeepAspect(true); setStripMetadata(false); }
  }

  async function convert() {
    if (!canConvert || busy) return;
    setBusy(true);
    setResult(null);
    const options = { format, quality, width: width || undefined, height: height || undefined, keep_aspect: keepAspect, strip_metadata: stripMetadata, prefix, suffix };
    try {
      const next = mode === "server"
        ? await imageConverterClient.convertDirectory({ source_directory: sourceDirectory, output_directory: outputDirectory || undefined, recursive, overwrite_policy: overwritePolicy, ...options })
        : await imageConverterClient.convertUpload(files, options);
      setResult(next);
      toast(`${tx.converted}: ${next.converted.length}`, "ok");
    } catch (error) {
      toast(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  const selectedFormat = formats.find((item) => item.id === format);
  const canRun = canConvert && !busy && (mode === "server" ? Boolean(sourceDirectory) : files.length > 0);
  const sourceCount = mode === "server" ? (browser?.images.length ?? 0) : files.length;
  const selectedBytes = files.reduce((sum, file) => sum + file.size, 0);

  return <section className="image-converter-app">
    <header className="image-converter-hero">
      <div className="image-converter-hero-icon"><Images aria-hidden="true" /></div>
      <div className="image-converter-hero-copy"><span className="image-converter-eyebrow">WebNAS Tools</span><h2>{tx.title}</h2><p>{tx.subtitle}</p></div>
      <div className={`image-converter-ready ${canRun ? "is-ready" : ""}`}><span className="image-converter-ready-dot" />{canRun ? tx.ready : tx.chooseSource}</div>
    </header>

    <div className="image-converter-tabs" role="tablist" aria-label={tx.source}>
      <button role="tab" aria-selected={mode === "server"} className={mode === "server" ? "active" : ""} onClick={() => { setMode("server"); setResult(null); }}><FolderOpen aria-hidden="true" /><span><strong>{tx.server}</strong><small>{pl ? "Pracuj bezpośrednio na plikach WebNAS" : "Work directly with WebNAS files"}</small></span></button>
      <button role="tab" aria-selected={mode === "upload"} className={mode === "upload" ? "active" : ""} onClick={() => { setMode("upload"); setResult(null); }}><Upload aria-hidden="true" /><span><strong>{tx.upload}</strong><small>{pl ? "Pliki są przechowywane tylko tymczasowo" : "Files are stored temporarily only"}</small></span></button>
    </div>

    {!canConvert && <div className="image-converter-warning"><AlertTriangle aria-hidden="true" /> {tx.noPermission}</div>}

    <div className="image-converter-layout">
      <main className="image-converter-main">
        <section className="image-converter-card">
          <div className="image-converter-card-heading"><div><span className="image-converter-step">1</span><div><h3>{tx.source}</h3><p>{mode === "server" ? tx.server : tx.upload}</p></div></div><span className="image-converter-count"><FileImage aria-hidden="true" /> {sourceCount}</span></div>
          {mode === "server" ? <div className="image-converter-source-content">
            <label className="image-converter-label">{tx.current}<div className="image-converter-path-row"><input value={sourceDirectory} onChange={(event) => setSourceDirectory(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadDirectory(sourceDirectory); }} /><button type="button" onClick={() => void loadDirectory(sourceDirectory)} disabled={busy}><FolderOpen aria-hidden="true" /><span>{busy ? tx.loading : pl ? "Otwórz" : "Open"}</span></button></div></label>
            <div className="image-converter-browser"><div className="image-converter-browser-toolbar"><strong>{browser?.path || sourceDirectory}</strong>{browser?.parent && <button className="image-converter-up" onClick={() => void loadDirectory(browser.parent!)}>↰ {tx.folderUp}</button>}</div><div className="image-converter-browser-body">{browser?.directories.map((directory) => <button key={directory.path} className="image-converter-folder" onClick={() => void loadDirectory(directory.path)}><FolderOpen aria-hidden="true" /><span>{directory.name}</span></button>)}<div className="image-converter-image-list"><div className="image-converter-list-title"><strong>{tx.images}</strong><span>{browser?.images.length ?? 0}</span></div>{browser?.images.length ? browser.images.slice(0, 100).map((image) => <div key={image.path}><span><FileImage aria-hidden="true" /> {image.name}</span><small>{formatBytes(image.size)}</small></div>) : <div className="image-converter-empty"><Images aria-hidden="true" /><span>{tx.emptyDirectory}</span></div>}</div>{browser?.truncated && <small className="image-converter-note"><Info aria-hidden="true" /> {tx.truncated}</small>}</div></div>
            <div className="image-converter-source-footer"><label className="image-converter-label">{tx.output}<input value={outputDirectory} onChange={(event) => setOutputDirectory(event.target.value)} placeholder={`${sourceDirectory}/converted-${format}`} /><small>{tx.outputHint}</small></label><label className="image-converter-toggle"><input type="checkbox" checked={recursive} onChange={(event) => setRecursive(event.target.checked)} /><span className="image-converter-toggle-control" /><span>{tx.recursive}</span></label></div>
          </div> : <div className="image-converter-source-content"><div className={`image-converter-drop ${dragActive ? "is-dragging" : ""}`} onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }} onDragOver={(event) => { event.preventDefault(); setDragActive(true); }} onDragLeave={(event) => { event.preventDefault(); if (event.currentTarget === event.target) setDragActive(false); }} onDrop={onDrop}><div className="image-converter-drop-icon"><Upload aria-hidden="true" /></div><strong>{tx.dropTitle}</strong><p>{tx.drop}</p><small className="image-converter-limit-note">{pl ? `Maks. ${limits.max_upload_files} plików · ${formatBytes(limits.max_file_bytes)} / plik · ${formatBytes(limits.max_batch_bytes)} łącznie` : `Max ${limits.max_upload_files} files · ${formatBytes(limits.max_file_bytes)} / file · ${formatBytes(limits.max_batch_bytes)} total`}</small><div className="image-converter-file-actions"><label className="image-converter-button image-converter-button-primary"><FileImage aria-hidden="true" /> {tx.chooseFiles}<input hidden type="file" accept="image/*,.heic,.heif,.avif" multiple onChange={(event) => { appendFiles(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} /></label><button className="image-converter-button" onClick={() => directoryInput.current?.click()}><FolderOpen aria-hidden="true" /> {tx.chooseLocalDirectory}</button><input ref={directoryInput} hidden type="file" accept="image/*,.heic,.heif,.avif" multiple onChange={(event) => { appendFiles(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} /></div></div>{files.length > 0 && <div className="image-converter-selected"><div className="image-converter-list-title"><strong>{tx.selected}</strong><div className="image-converter-selection-meta"><span>{files.length}</span><small>{formatBytes(selectedBytes)}</small><button onClick={() => { setFiles([]); setResult(null); }}>{tx.clear}</button></div></div>{files.slice(0, 20).map((file, index) => <p key={fileIdentity(file)}><span><FileImage aria-hidden="true" /> {(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}</span><span className="image-converter-selected-actions"><small>{formatBytes(file.size)}</small><button type="button" className="image-converter-remove" title={tx.remove} aria-label={`${tx.remove}: ${file.name}`} onClick={() => removeFile(index)}><XCircle aria-hidden="true" /></button></span></p>)}{files.length > 20 && <small className="image-converter-note">+{files.length - 20}</small>}</div>}</div>}
        </section>

        {result && <section className="image-converter-card image-converter-result"><div className="image-converter-card-heading"><div><span className="image-converter-step image-converter-step-success"><CheckCircle2 aria-hidden="true" /></span><div><h3>{tx.result}</h3><p>{pl ? "Podsumowanie ostatniej konwersji" : "Summary of the latest conversion"}</p></div></div>{result.download_url && <button className="image-converter-download" onClick={() => triggerDownload(result.download_url!)}><Download aria-hidden="true" /><span>{tx.download}</span></button>}</div><div className="image-converter-status-grid"><div className="success"><CheckCircle2 aria-hidden="true" /><span><small>{tx.converted}</small><strong>{result.converted.length}</strong></span></div><div className="warning"><Info aria-hidden="true" /><span><small>{tx.skipped}</small><strong>{result.skipped?.length ?? 0}</strong></span></div><div className="danger"><XCircle aria-hidden="true" /><span><small>{tx.failed}</small><strong>{result.failed.length}</strong></span></div></div>{result.summary && <div className="image-converter-summary"><span><small>{tx.sourceSize}</small><strong>{formatBytes(result.summary.source_bytes)}</strong></span><span><small>{tx.outputSize}</small><strong>{formatBytes(result.summary.output_bytes)}</strong></span><span><small>{tx.saved}</small><strong>{formatBytes(result.summary.saved_bytes)}</strong></span></div>}{result.output_directory && <div className="image-converter-output-path"><FolderOpen aria-hidden="true" /><code>{result.output_directory}</code></div>}{result.converted.length > 0 && <details className="image-converter-details"><summary>{tx.details}</summary>{result.converted.slice(0, 100).map((item) => <p key={item.output}><code>{item.output}</code><span>{item.width}×{item.height} · {formatBytes(item.size)}</span></p>)}</details>}{result.failed.length > 0 && <details className="image-converter-details image-converter-details-danger"><summary>{tx.failuresDetails}</summary>{result.failed.map((failure, index) => <p key={`${failure.source}:${index}`}><code>{failure.source}</code><span>{failure.message}</span></p>)}</details>}</section>}
      </main>

      <aside className="image-converter-options image-converter-card"><div className="image-converter-card-heading compact"><div><span className="image-converter-step">2</span><div><h3>{tx.settings}</h3><p>{pl ? "Format i optymalizacja" : "Format and optimization"}</p></div></div><SlidersHorizontal aria-hidden="true" /></div><label className="image-converter-label">{tx.presets}<select value="" onChange={(event) => { if (event.target.value) applyPreset(event.target.value as Preset); }}><option value="">—</option><option value="balanced">{tx.balanced}</option><option value="web">{tx.web}</option><option value="high">{tx.high}</option></select></label><label className="image-converter-label">{tx.format}<select value={format} onChange={(event) => setFormat(event.target.value)}>{(formats.length ? formats : [{ id: "webp", extension: ".webp", lossy: true }]).map((item) => <option key={item.id} value={item.id}>{item.id.toUpperCase()} ({item.extension})</option>)}</select></label>{selectedFormat?.lossy !== false && <label className="image-converter-label image-converter-quality"><span>{tx.quality}<strong>{quality}%</strong></span><input type="range" min="1" max="100" value={quality} onChange={(event) => setQuality(Number(event.target.value))} /></label>}<details className="image-converter-advanced" open><summary><Gauge aria-hidden="true" /> {tx.resize}</summary><div className="image-converter-advanced-body"><div className="image-converter-grid2"><label className="image-converter-label">{tx.width}<input type="number" min="1" max={limits.max_dimension} placeholder={tx.originalSize} value={width || ""} onChange={(event) => setWidth(Number(event.target.value) || 0)} /></label><label className="image-converter-label">{tx.height}<input type="number" min="1" max={limits.max_dimension} placeholder={tx.originalSize} value={height || ""} onChange={(event) => setHeight(Number(event.target.value) || 0)} /></label></div><label className="image-converter-toggle"><input type="checkbox" checked={keepAspect} onChange={(event) => setKeepAspect(event.target.checked)} /><span className="image-converter-toggle-control" /><span>{tx.keepAspect}</span></label></div></details><details className="image-converter-advanced"><summary><SlidersHorizontal aria-hidden="true" /> {tx.advanced}</summary><div className="image-converter-advanced-body"><div className="image-converter-grid2"><label className="image-converter-label">{tx.prefix}<input maxLength={80} value={prefix} onChange={(event) => setPrefix(event.target.value)} /></label><label className="image-converter-label">{tx.suffix}<input maxLength={80} value={suffix} onChange={(event) => setSuffix(event.target.value)} /></label></div>{mode === "server" && <label className="image-converter-label">{tx.collision}<select value={overwritePolicy} onChange={(event) => setOverwritePolicy(event.target.value as OverwritePolicy)}><option value="rename">{tx.rename}</option><option value="skip">{tx.skip}</option><option value="overwrite">{tx.overwrite}</option></select></label>}<label className="image-converter-toggle"><input type="checkbox" checked={stripMetadata} onChange={(event) => setStripMetadata(event.target.checked)} /><span className="image-converter-toggle-control" /><span>{tx.stripMetadata}</span></label></div></details><div className="image-converter-run-summary"><span><FileImage aria-hidden="true" /> {sourceCount} {pl ? "plików" : "files"}</span><span>→</span><strong>{format.toUpperCase()}</strong></div><button className="image-converter-primary" disabled={!canRun} onClick={() => void convert()}><WandSparkles aria-hidden="true" /> {busy ? tx.converting : tx.convert}</button></aside>
    </div>
  </section>;
}
