import { Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type FileItem } from "../../api";
import type { Translate } from "../../app/types";
import { ConfirmDialog, Modal } from "../../components/Modal";

const MAX_TEXT_FILE_BYTES = 1024 * 1024;

function editorError(error: unknown, t: Translate) {
  if (error instanceof ApiError) {
    if (error.code === "binary_file") return t("editor.binary");
    if (error.code === "file_too_large") return t("editor.tooLarge");
    if (error.code === "changed_on_disk") return t("editor.changedOnDisk");
    if (error.code === "not_regular_file") return t("editor.notRegularFile");
  }
  return error instanceof Error ? error.message : t("editor.loadError");
}


export function TextEditor({ item, t, onClose, onSaved }: {
  item: FileItem;
  t: Translate;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [value, setValue] = useState("");
  const [original, setOriginal] = useState("");
  const [version, setVersion] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const dirty = !loading && value !== original;
  const readOnly = !item.can_write;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setSaved(false);
    try {
      const result = await api.readText(item.path);
      setValue(result.content);
      setOriginal(result.content);
      setVersion(result.mtime_ns);
      window.setTimeout(() => textarea.current?.focus(), 0);
    } catch (reason) {
      setError(editorError(reason, t));
    } finally {
      setLoading(false);
    }
  }, [item.path, t]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  const save = useCallback(async () => {
    if (readOnly || !dirty || saving || !version) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const result = await api.writeText(item.path, value, version);
      setOriginal(value);
      setVersion(result.mtime_ns);
      setSaved(true);
      onSaved();
    } catch (reason) {
      setError(editorError(reason, t));
    } finally {
      setSaving(false);
    }
  }, [dirty, item.path, onSaved, readOnly, saving, t, value, version]);

  const requestClose = useCallback(() => {
    if (dirty) setConfirmClose(true);
    else onClose();
  }, [dirty, onClose]);
  const lineCount = useMemo(() => value ? value.split("\n").length : 1, [value]);

  return <>
    <Modal title={`${t("files.textEditor")} — ${item.name}`} closeLabel={t("action.close")} onClose={requestClose} wide footer={<>
      <span className={`text-editor-status ${error ? "error" : ""}`}>{error || (readOnly ? t("editor.readOnly") : saved ? t("editor.saved") : dirty ? t("editor.unsaved") : t("status.ready"))}</span>
      {error && !version && <button type="button" onClick={() => void load()}>{t("action.retry")}</button>}
      <button type="button" onClick={requestClose}>{t("action.close")}</button>
      <button className="button-primary" type="button" disabled={readOnly || loading || saving || !dirty} onClick={() => void save()}><Save />{saving ? t("editor.saving") : t("action.save")}</button>
    </>}>
      <div className="text-editor">
        {loading ? <div className="loading-state">{t("status.loading")}</div> : error && !version ? <div className="error-state">{error}</div> : <textarea
          ref={textarea}
          aria-label={t("editor.content")}
          value={value}
          readOnly={readOnly}
          spellCheck={false}
          onChange={(event) => {
            const next = event.target.value;
            if (new TextEncoder().encode(next).byteLength > MAX_TEXT_FILE_BYTES) { setError(t("editor.tooLarge")); return; }
            setValue(next);
            setSaved(false);
            setError("");
          }}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); void save(); return; }
            if (event.key === "Tab" && !readOnly) {
              event.preventDefault();
              const target = event.currentTarget;
              const start = event.currentTarget.selectionStart;
              const end = event.currentTarget.selectionEnd;
              setValue((current) => `${current.slice(0, start)}\t${current.slice(end)}`);
              window.setTimeout(() => { target.selectionStart = target.selectionEnd = start + 1; }, 0);
            }
          }}
        />}
        <footer><span>UTF-8</span><span>{t("editor.lines").replace("{count}", String(lineCount))}</span><span>{t("editor.characters").replace("{count}", String(value.length))}</span></footer>
      </div>
    </Modal>
    {confirmClose && <ConfirmDialog title={t("editor.closeTitle")} message={t("editor.closeMessage")} confirmLabel={t("editor.discard")} cancelLabel={t("action.cancel")} danger onClose={() => setConfirmClose(false)} onConfirm={onClose} />}
  </>;
}
