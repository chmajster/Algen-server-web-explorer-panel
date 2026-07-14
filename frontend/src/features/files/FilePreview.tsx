import { Download, Expand, RotateCw, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, downloadUrl, type FileItem } from "../../api";
import type { Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { formatSize } from "./utils";

function decode(base64: string) {
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

export function FilePreview({ item, t, onClose }: { item: FileItem; t: Translate; onClose: () => void }) {
  const [data, setData] = useState<{ mime: string; content: string } | null>(null);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  useEffect(() => { api.preview(item.path).then((result) => setData({ mime: result.mime, content: result.content_base64 })).catch((reason) => setError(reason instanceof Error ? reason.message : t("files.previewError"))); }, [item.path, t]);
  const source = data ? `data:${data.mime};base64,${data.content}` : "";
  const text = useMemo(() => data ? decode(data.content) : "", [data]);
  const isText = data?.mime.startsWith("text/") || data?.mime.includes("json") || /\.(log|json|txt|md|csv|ya?ml)$/i.test(item.name);
  const looksBinary = isText && text.slice(0, 4096).includes(String.fromCharCode(0));
  return <Modal title={item.name} closeLabel={t("action.close")} onClose={onClose} wide footer={<div className="preview-footer"><span>{formatSize(item.size)} · {data?.mime || item.mime || item.type}</span><a className="button-primary" href={downloadUrl(item.path)}><Download />{t("action.download")}</a></div>}>
    <div className="preview-toolbar"><button onClick={() => setZoom((value) => Math.min(4, value + .25))}><ZoomIn />{t("preview.zoomIn")}</button><button onClick={() => setZoom((value) => Math.max(.25, value - .25))}><ZoomOut />{t("preview.zoomOut")}</button><button onClick={() => setRotation((value) => value + 90)}><RotateCw />{t("preview.rotate")}</button><button onClick={() => document.documentElement.requestFullscreen?.()}><Expand />{t("preview.fullscreen")}</button></div>
    <div className="preview-stage">{error ? <p className="error-state">{error}</p> : !data ? <div className="loading-state">{t("status.loading")}</div> : data.mime.startsWith("image/") ? <img src={source} alt={item.name} style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }} /> : data.mime === "application/pdf" ? <iframe title={item.name} src={source} /> : isText && !looksBinary ? <pre>{text}</pre> : <div className="empty-state"><strong>{t("preview.unsupported")}</strong><span>{looksBinary ? t("preview.binary") : data.mime}</span></div>}</div>
  </Modal>;
}
