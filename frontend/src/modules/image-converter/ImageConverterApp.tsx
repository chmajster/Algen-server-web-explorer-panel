import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Download, FolderOpen, Images, Upload, WandSparkles } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { imageConverterClient } from "./api/client";
import type { ConversionResult, DirectoryBrowser, ImageFormat } from "./api/client";
import "./image-converter.css";

type InputMode = "server" | "upload";
type OverwritePolicy = "rename" | "skip" | "overwrite";

function formatBytes(value: number) {
  const negative = value < 0;
  const absolute = Math.abs(value);
  const formatted = absolute < 1024 ? `${absolute} B` : absolute < 1024 * 1024 ? `${(absolute / 1024).toFixed(1)} KB` : `${(absolute / (1024 * 1024)).toFixed(1)} MB`;
  return negative ? `-${formatted}` : formatted;
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
    subtitle: pl ? "Konwertuj, skaluj i optymalizuj zdjęcia z katalogu na serwerze albo z plików tymczasowych." : "Convert, resize and optimize images from a server directory or temporary uploads.",
    server: pl ? "Katalog na serwerze" : "Server directory",
    upload: pl ? "Pliki tymczasowe" : "Temporary files",
    current: pl ? "Wybrany katalog" : "Selected directory",
    output: pl ? "Katalog wynikowy" : "Output directory",
    outputHint: pl ? "Puste pole utworzy katalog converted-FORMAT obok źródeł." : "Leave empty to create a converted-FORMAT directory next to the sources.",
    recursive: pl ? "Uwzględnij podkatalogi" : "Include subdirectories",
    images: pl ? "Obrazy" : "Images",
    emptyDirectory: pl ? "W tym katalogu nie ma obsługiwanych obrazów." : "No supported images in this directory.",
    chooseFiles: pl ? "Wybierz zdjęcia" : "Choose images",
    chooseLocalDirectory: pl ? "Wybierz katalog z komputera" : "Choose local directory",
    drop: pl ? "Przeciągnij zdjęcia tutaj lub użyj przycisków wyboru." : "Drop images here or use the selection buttons.",
    selected: pl ? "Wybrano" : "Selected",
    clear: pl ? "Wyczyść" : "Clear",
    format: pl ? "Format wynikowy" : "Output format",
    quality: pl ? "Jakość" : "Quality",
    resize: pl ? "Zmiana rozmiaru" : "Resize",
    width: pl ? "Szerokość" : "Width",
    height: pl ? "Wysokość" : "Height",
    originalSize: pl ? "Oryginalny rozmiar" : "Original size",
    keepAspect: pl ? "Zachowaj proporcje" : "Keep aspect ratio",
    stripMetadata: pl ? "Usuń metadane EXIF/ICC" : "Strip EXIF/ICC metadata",
    naming: pl ? "Nazwy plików" : "File naming",
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
    convert: pl ? "Konwertuj" : "Convert",
    converting: pl ? "Konwertowanie…" : "Converting…",
    converted: pl ? "Przekonwertowano" : "Converted",
    failed: pl ? "Błędy" : "Failed",
    skipped: pl ? "Pominięto" : "Skipped",
    download: pl ? "Pobierz ZIP" : "Download ZIP",
    sourceSize: pl ? "Rozmiar wejściowy" : "Input size",
    outputSize: pl ? "Rozmiar wynikowy" : "Output size",
    saved: pl ? "Różnica" : "Difference",
    noPermission: pl ? "Nie masz uprawnienia do konwersji obrazów." : "You do not have permission to convert images.",
    folderUp: pl ? "Katalog wyżej" : "Parent directory",
    truncated: pl ? "Lista została ograniczona do pierwszych 1000 pozycji." : "The list was limited to the first 1000 entries.",
  };
  const canConvert = permissions.includes("image_converter.convert");
  const [mode, setMode] = useState<InputMode>("server");
  const [formats, setFormats] = useState<ImageFormat[]>([]);
  const [format, setFormat] = useState("webp");
  const [quality, setQuality] = useState(90);
  const [browser, setBrowser] = useState<DirectoryBrowser | null>(null);
  const [sourceDirectory, setSourceDirectory] = useState(homePath);
  const [outputDirectory, setOutputDirectory] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
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
    void imageConverterClient.formats().then(({ formats: available }) => {
      setFormats(available);
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
    setFiles((current) => {
      const seen = new Set(current.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
      const merged = [...current];
      for (const file of next) {
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (!seen.has(key)) { seen.add(key); merged.push(file); }
      }
      return merged.slice(0, 100);
    });
    setResult(null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    appendFiles(Array.from(event.dataTransfer.files));
  }

  function applyPreset(preset: "balanced" | "web" | "high") {
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
      toast(`${tx.converted}: ${next.converted.length}`, "success");
    } catch (error) {
      toast(String(error), "error");
    } finally {
      setBusy(false);
    }
  }

  const selectedFormat = formats.find((item) => item.id === format);
  const canRun = canConvert && !busy && (mode === "server" ? Boolean(sourceDirectory) : files.length > 0);

  return <section className="image-converter-app">
    <header className="image-converter-header"><div><span className="image-converter-eyebrow">WebNAS Tools</span><h2><Images aria-hidden="true" /> {tx.title}</h2><p>{tx.subtitle}</p></div></header>

    <div className="image-converter-modes" role="tablist">
      <button className={mode === "server" ? "active" : ""} onClick={() => { setMode("server"); setResult(null); }}><FolderOpen aria-hidden="true" /> {tx.server}</button>
      <button className={mode === "upload" ? "active" : ""} onClick={() => { setMode("upload"); setResult(null); }}><Upload aria-hidden="true" /> {tx.upload}</button>
    </div>

    {!canConvert && <div className="image-converter-warning">{tx.noPermission}</div>}

    <div className="image-converter-layout">
      <div className="image-converter-panel">
        {mode === "server" ? <>
          <label>{tx.current}<input value={sourceDirectory} onChange={(event) => setSourceDirectory(event.target.value)} onBlur={() => void loadDirectory(sourceDirectory)} /></label>
          <div className="image-converter-browser">
            {browser?.parent && <button className="image-converter-folder" onClick={() => void loadDirectory(browser.parent!)}>↰ {tx.folderUp}</button>}
            {browser?.directories.map((directory) => <button key={directory.path} className="image-converter-folder" onClick={() => void loadDirectory(directory.path)}><FolderOpen aria-hidden="true" /> {directory.name}</button>)}
            <div className="image-converter-image-list"><strong>{tx.images}: {browser?.images.length ?? 0}</strong>{browser?.images.length ? browser.images.slice(0, 100).map((image) => <div key={image.path}><span>{image.name}</span><small>{formatBytes(image.size)}</small></div>) : <p>{tx.emptyDirectory}</p>}</div>
            {browser?.truncated && <small>{tx.truncated}</small>}
          </div>
          <label>{tx.output}<input value={outputDirectory} onChange={(event) => setOutputDirectory(event.target.value)} placeholder={`${sourceDirectory}/converted-${format}`} /><small>{tx.outputHint}</small></label>
          <label className="image-converter-check"><input type="checkbox" checked={recursive} onChange={(event) => setRecursive(event.target.checked)} /> {tx.recursive}</label>
        </> : <>
          <div className="image-converter-drop" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
            <Upload aria-hidden="true" /><p>{tx.drop}</p>
            <div className="image-converter-file-actions">
              <label className="image-converter-button">{tx.chooseFiles}<input hidden type="file" accept="image/*,.heic,.heif,.avif" multiple onChange={(event) => appendFiles(Array.from(event.target.files || []))} /></label>
              <button className="image-converter-button" onClick={() => directoryInput.current?.click()}>{tx.chooseLocalDirectory}</button>
              <input ref={directoryInput} hidden type="file" accept="image/*,.heic,.heif,.avif" multiple onChange={(event) => appendFiles(Array.from(event.target.files || []))} />
            </div>
          </div>
          <div className="image-converter-selected"><div><strong>{tx.selected}: {files.length}</strong>{files.length > 0 && <button onClick={() => setFiles([])}>{tx.clear}</button>}</div>{files.slice(0, 20).map((file, index) => <p key={`${file.name}:${file.size}:${index}`}><span>{file.name}</span><small>{formatBytes(file.size)}</small></p>)}{files.length > 20 && <small>+{files.length - 20}</small>}</div>
        </>}
      </div>

      <aside className="image-converter-options">
        <label>{tx.presets}<select defaultValue="" onChange={(event) => { if (event.target.value) applyPreset(event.target.value as "balanced" | "web" | "high"); }}><option value="">—</option><option value="balanced">{tx.balanced}</option><option value="web">{tx.web}</option><option value="high">{tx.high}</option></select></label>
        <label>{tx.format}<select value={format} onChange={(event) => setFormat(event.target.value)}>{(formats.length ? formats : [{ id: "webp", extension: ".webp", lossy: true }]).map((item) => <option key={item.id} value={item.id}>{item.id.toUpperCase()} ({item.extension})</option>)}</select></label>
        {selectedFormat?.lossy !== false && <label>{tx.quality}: {quality}<input type="range" min="1" max="100" value={quality} onChange={(event) => setQuality(Number(event.target.value))} /></label>}

        <fieldset className="image-converter-fieldset"><legend>{tx.resize}</legend><div className="image-converter-grid2"><label>{tx.width}<input type="number" min="1" max="32768" placeholder={tx.originalSize} value={width || ""} onChange={(event) => setWidth(Number(event.target.value) || 0)} /></label><label>{tx.height}<input type="number" min="1" max="32768" placeholder={tx.originalSize} value={height || ""} onChange={(event) => setHeight(Number(event.target.value) || 0)} /></label></div><label className="image-converter-check"><input type="checkbox" checked={keepAspect} onChange={(event) => setKeepAspect(event.target.checked)} /> {tx.keepAspect}</label></fieldset>

        <fieldset className="image-converter-fieldset"><legend>{tx.naming}</legend><div className="image-converter-grid2"><label>{tx.prefix}<input maxLength={80} value={prefix} onChange={(event) => setPrefix(event.target.value)} /></label><label>{tx.suffix}<input maxLength={80} value={suffix} onChange={(event) => setSuffix(event.target.value)} /></label></div>{mode === "server" && <label>{tx.collision}<select value={overwritePolicy} onChange={(event) => setOverwritePolicy(event.target.value as OverwritePolicy)}><option value="rename">{tx.rename}</option><option value="skip">{tx.skip}</option><option value="overwrite">{tx.overwrite}</option></select></label>}</fieldset>

        <label className="image-converter-check"><input type="checkbox" checked={stripMetadata} onChange={(event) => setStripMetadata(event.target.checked)} /> {tx.stripMetadata}</label>
        <button className="image-converter-primary" disabled={!canRun} onClick={() => void convert()}><WandSparkles aria-hidden="true" /> {busy ? tx.converting : tx.convert}</button>
      </aside>
    </div>

    {result && <section className="image-converter-result">
      <div><strong>{tx.converted}: {result.converted.length}</strong><span>{tx.failed}: {result.failed.length}</span><span>{tx.skipped}: {result.skipped?.length ?? 0}</span>{result.output_directory && <code>{result.output_directory}</code>}</div>
      {result.summary && <div className="image-converter-summary"><span><small>{tx.sourceSize}</small><strong>{formatBytes(result.summary.source_bytes)}</strong></span><span><small>{tx.outputSize}</small><strong>{formatBytes(result.summary.output_bytes)}</strong></span><span><small>{tx.saved}</small><strong>{formatBytes(result.summary.saved_bytes)}</strong></span></div>}
      {result.converted.length > 0 && <details><summary>{tx.converted}</summary>{result.converted.slice(0, 100).map((item) => <p key={item.output}><code>{item.output}</code> — {item.width}×{item.height}, {formatBytes(item.size)}</p>)}</details>}
      {result.download_url && <button onClick={() => triggerDownload(result.download_url!)}><Download aria-hidden="true" /> {tx.download}</button>}
      {result.failed.length > 0 && <details><summary>{tx.failed}</summary>{result.failed.map((failure, index) => <p key={`${failure.source}:${index}`}><code>{failure.source}</code> — {failure.message}</p>)}</details>}
    </section>}
  </section>;
}
