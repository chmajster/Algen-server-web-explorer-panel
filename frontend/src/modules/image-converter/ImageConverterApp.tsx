import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { Download, FolderOpen, Images, Upload, WandSparkles } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { imageConverterClient } from "./api/client";
import type { ConversionResult, DirectoryBrowser, ImageFormat } from "./api/client";
import "./image-converter.css";

type InputMode = "server" | "upload";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
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
    subtitle: pl ? "Konwertuj zdjęcia z katalogu na serwerze albo prześlij je tylko na czas konwersji." : "Convert images from an allowed server directory or upload them only for the duration of the conversion.",
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
    convert: pl ? "Konwertuj" : "Convert",
    converting: pl ? "Konwertowanie…" : "Converting…",
    converted: pl ? "Przekonwertowano" : "Converted",
    failed: pl ? "Błędy" : "Failed",
    download: pl ? "Pobierz ZIP" : "Download ZIP",
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
  const directoryInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    directoryInput.current?.setAttribute("webkitdirectory", "");
    void imageConverterClient.formats().then(({ formats: available }) => {
      setFormats(available);
      if (available.length && !available.some((item) => item.id === format)) setFormat(available[0].id);
    }).catch((error) => toast(String(error), "error"));
  }, []);

  async function loadDirectory(path: string) {
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
  }

  useEffect(() => { void loadDirectory(homePath); }, [homePath]);

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

  async function convert() {
    if (!canConvert || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const next = mode === "server"
        ? await imageConverterClient.convertDirectory({ source_directory: sourceDirectory, output_directory: outputDirectory || undefined, format, quality, recursive })
        : await imageConverterClient.convertUpload(files, format, quality);
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
    <header className="image-converter-header">
      <div><span className="image-converter-eyebrow">WebNAS Tools</span><h2><Images aria-hidden="true" /> {tx.title}</h2><p>{tx.subtitle}</p></div>
    </header>

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
            <div className="image-converter-image-list">
              <strong>{tx.images}: {browser?.images.length ?? 0}</strong>
              {browser?.images.length ? browser.images.slice(0, 100).map((image) => <div key={image.path}><span>{image.name}</span><small>{formatBytes(image.size)}</small></div>) : <p>{tx.emptyDirectory}</p>}
            </div>
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
          <div className="image-converter-selected">
            <div><strong>{tx.selected}: {files.length}</strong>{files.length > 0 && <button onClick={() => setFiles([])}>{tx.clear}</button>}</div>
            {files.slice(0, 20).map((file, index) => <p key={`${file.name}:${file.size}:${index}`}><span>{file.name}</span><small>{formatBytes(file.size)}</small></p>)}
            {files.length > 20 && <small>+{files.length - 20}</small>}
          </div>
        </>}
      </div>

      <aside className="image-converter-options">
        <label>{tx.format}<select value={format} onChange={(event) => setFormat(event.target.value)}>{(formats.length ? formats : [{ id: "webp", extension: ".webp", lossy: true }]).map((item) => <option key={item.id} value={item.id}>{item.id.toUpperCase()} ({item.extension})</option>)}</select></label>
        {selectedFormat?.lossy !== false && <label>{tx.quality}: {quality}<input type="range" min="1" max="100" value={quality} onChange={(event) => setQuality(Number(event.target.value))} /></label>}
        <button className="image-converter-primary" disabled={!canRun} onClick={() => void convert()}><WandSparkles aria-hidden="true" /> {busy ? tx.converting : tx.convert}</button>
      </aside>
    </div>

    {result && <section className="image-converter-result">
      <div><strong>{tx.converted}: {result.converted.length}</strong><span>{tx.failed}: {result.failed.length}</span>{result.output_directory && <code>{result.output_directory}</code>}</div>
      {result.download_url && <button onClick={() => triggerDownload(result.download_url!)}><Download aria-hidden="true" /> {tx.download}</button>}
      {result.failed.length > 0 && <details><summary>{tx.failed}</summary>{result.failed.map((failure, index) => <p key={`${failure.source}:${index}`}><code>{failure.source}</code> — {failure.message}</p>)}</details>}
    </section>}
  </section>;
}
