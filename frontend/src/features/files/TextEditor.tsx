import { indentWithTab } from "@codemirror/commands";
import { gotoLine, openSearchPanel } from "@codemirror/search";
import { Compartment, EditorState, Text } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { basicSetup, EditorView } from "codemirror";
import { Download, ListOrdered, RefreshCw, Save, Search, WrapText } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type FileItem } from "../../api";
import type { Translate } from "../../app/types";
import { ConfirmDialog, Modal } from "../../components/Modal";
import "./TextEditor.css";

const MAX_TEXT_FILE_BYTES = 1024 * 1024;
const separators = { LF: "\n", CRLF: "\r\n", CR: "\r" } as const;
type LineEnding = keyof typeof separators | "mixed";
type EditorOptions = { readOnly: boolean; lineEnding: LineEnding; wrap: boolean; t: Translate };
type TextEditorProps = { item: FileItem; t: Translate; onClose: () => void; onSaved: () => void };

function detectLineEnding(content: string): LineEnding {
  const endings = new Set(content.match(/\r\n|\r|\n/g));
  if (endings.size > 1) return "mixed";
  if (endings.has("\r\n")) return "CRLF";
  return endings.has("\r") ? "CR" : "LF";
}

function documentOptions({ readOnly, lineEnding }: EditorOptions) {
  const locked = readOnly || lineEnding === "mixed";
  return [EditorState.readOnly.of(locked), EditorView.editable.of(!locked)];
}

function serializeDocument(doc: Text, lineEnding: LineEnding) {
  // Keep CodeMirror's universal newline parsing for paste, Enter and replace.
  // Apply the file's chosen ending only when serializing the document.
  return doc.sliceString(0, doc.length, lineEnding === "mixed" ? "\n" : separators[lineEnding]);
}

function languageOptions(t: Translate) {
  const phrases = Object.fromEntries([
    ["Find", "find"], ["Replace", "replaceInput"], ["next", "next"], ["previous", "previous"],
    ["all", "all"], ["match case", "matchCase"], ["regexp", "regexp"], ["by word", "wholeWord"],
    ["replace", "replace"], ["replace all", "replaceAll"], ["close", "close"],
    ["Go to line", "goToLine"], ["go", "go"], ["current match", "currentMatch"],
    ["on line", "onLine"], ["replaced match on line $", "replacedOnLine"], ["replaced $ matches", "replacedMatches"],
  ].map(([phrase, key]) => [phrase, t(`editor.search.${key}`)]));
  return [EditorState.phrases.of(phrases), EditorView.contentAttributes.of({
    "aria-label": t("editor.content"), "aria-description": t("editor.keyboardHint"),
    "data-testid": "text-editor-input", spellcheck: "false",
  })];
}

function editorError(error: unknown, t: Translate) {
  if (error instanceof ApiError) {
    if (error.code === "binary_file") return t("editor.binary");
    if (error.code === "file_too_large") return t("editor.tooLarge");
    if (error.code === "changed_on_disk") return t("editor.changedOnDisk");
    if (error.code === "not_regular_file") return t("editor.notRegularFile");
  }
  return error instanceof Error ? error.message : t("editor.loadError");
}

export function TextEditor(props: TextEditorProps) {
  // A different file owns a different draft, request lifecycle and undo history.
  return <TextEditorSession key={props.item.path} {...props} />;
}

function TextEditorSession({ item, t, onClose, onSaved }: TextEditorProps) {
  const [value, setValue] = useState("");
  const [original, setOriginal] = useState("");
  const [version, setVersion] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [confirmation, setConfirmation] = useState<"close" | "reload" | null>(null);
  const [lineEnding, setLineEnding] = useState<LineEnding>("LF");
  const [wrap, setWrap] = useState(false);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [compartments] = useState(() => ({ document: new Compartment(), language: new Compartment(), wrap: new Compartment() }));
  const editorHost = useRef<HTMLDivElement>(null);
  const editorView = useRef<EditorView | null>(null);
  const valueRef = useRef("");
  const baseline = useRef({ content: "", version: "" });
  const savingRef = useRef(false);
  const loadingRef = useRef(true);
  const mounted = useRef(false);
  const readController = useRef<AbortController | null>(null);
  const saveRef = useRef<() => void>(() => undefined);
  const options = useRef<EditorOptions>({ readOnly: !item.can_write, lineEnding: "LF", wrap: false, t });
  const dirty = !loading && value !== original;
  const readOnly = !item.can_write;
  const ready = !loading && Boolean(version);

  // Reconfigure the live editor without replacing its document or undo history.
  useEffect(() => {
    options.current = { readOnly, lineEnding, wrap, t };
    editorView.current?.dispatch({ effects: [
      compartments.document.reconfigure(documentOptions(options.current)),
      compartments.language.reconfigure(languageOptions(t)),
      compartments.wrap.reconfigure(wrap ? EditorView.lineWrapping : []),
    ] });
  }, [compartments, readOnly, lineEnding, wrap, t]);

  const load = useCallback(async () => {
    if (savingRef.current) return;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    loadingRef.current = true;
    setLoading(true);
    setError("");
    setSaved(false);
    try {
      const result = await api.readText(item.path, controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      valueRef.current = result.content;
      baseline.current = { content: result.content, version: result.mtime_ns };
      setValue(result.content);
      setOriginal(result.content);
      setVersion(result.mtime_ns);
      setLineEnding(detectLineEnding(result.content));
      setCursor({ line: 1, column: 1 });
    } catch (reason) {
      if (!controller.signal.aborted && mounted.current) setError(editorError(reason, options.current.t));
    } finally {
      if (!controller.signal.aborted && mounted.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [item.path]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => { mounted.current = false; readController.current?.abort(); };
  }, [load]);

  useEffect(() => {
    if (!dirty && !saving) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty, saving]);

  const save = useCallback(async () => {
    const current = valueRef.current;
    const expectedVersion = baseline.current.version;
    if (options.current.readOnly || current === baseline.current.content || savingRef.current || loadingRef.current || !expectedVersion) return;
    savingRef.current = true;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const result = await api.writeText(item.path, current, expectedVersion);
      if (!mounted.current) return;
      // Only the submitted snapshot was saved. Newer typing must remain dirty.
      baseline.current = { content: current, version: result.mtime_ns };
      setOriginal(current);
      setVersion(result.mtime_ns);
      setSaved(valueRef.current === current);
      onSaved();
    } catch (reason) {
      if (mounted.current) setError(editorError(reason, options.current.t));
    } finally {
      savingRef.current = false;
      if (mounted.current) setSaving(false);
    }
  }, [item.path, onSaved]);
  useEffect(() => { saveRef.current = () => { void save(); }; }, [save]);

  useEffect(() => {
    const host = editorHost.current;
    if (loading || !host) return;
    const currentOptions = options.current;
    const state = EditorState.create({
      doc: Text.of(valueRef.current.split(/\r\n|\r|\n/)),
      extensions: [
        basicSetup,
        compartments.document.of(documentOptions(currentOptions)),
        compartments.language.of(languageOptions(currentOptions.t)),
        compartments.wrap.of(currentOptions.wrap ? EditorView.lineWrapping : []),
        keymap.of([indentWithTab, {
          key: "Escape",
          run(view) { view.setTabFocusMode(2000); return true; },
        }]),
        EditorState.transactionFilter.of((transaction) => {
          if (!transaction.docChanged) return transaction;
          const next = serializeDocument(transaction.newDoc, options.current.lineEnding);
          if (new TextEncoder().encode(next).byteLength <= MAX_TEXT_FILE_BYTES) return transaction;
          queueMicrotask(() => { if (mounted.current) setError(options.current.t("editor.tooLarge")); });
          return [];
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            const next = serializeDocument(update.state.doc, options.current.lineEnding);
            valueRef.current = next;
            setValue(next);
            setSaved(false);
            setError("");
          }
          if (update.docChanged || update.selectionSet) {
            const head = update.state.selection.main.head;
            const line = update.state.doc.lineAt(head);
            setCursor({ line: line.number, column: head - line.from + 1 });
          }
        }),
        EditorView.domEventHandlers({
          keydown(event) {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              saveRef.current();
              return true;
            }
            return false;
          },
        }),
      ],
    });
    const view = new EditorView({ state, parent: host });
    editorView.current = view;
    const focusTimer = window.setTimeout(() => view.focus(), 0);
    return () => {
      window.clearTimeout(focusTimer);
      if (editorView.current === view) editorView.current = null;
      view.destroy();
    };
  }, [compartments, loading]);

  const requestClose = useCallback(() => {
    if (savingRef.current) return;
    if (valueRef.current !== baseline.current.content) setConfirmation("close");
    else onClose();
  }, [onClose]);

  const requestReload = () => {
    if (savingRef.current || loadingRef.current) return;
    if (valueRef.current !== baseline.current.content) setConfirmation("reload");
    else void load();
  };

  const changeLineEnding = (nextEnding: keyof typeof separators) => {
    const view = editorView.current;
    if (!view || readOnly || !ready) return;
    const next = serializeDocument(view.state.doc, nextEnding);
    if (new TextEncoder().encode(next).byteLength > MAX_TEXT_FILE_BYTES) {
      setError(t("editor.tooLarge"));
      return;
    }
    valueRef.current = next;
    setValue(next);
    setLineEnding(nextEnding);
    setSaved(false);
  };

  const downloadCopy = () => {
    const url = URL.createObjectURL(new Blob([valueRef.current], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = item.name;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const lineCount = useMemo(() => value.split(/\r\n|\r|\n/).length, [value]);

  return <>
    <Modal title={`${t("files.textEditor")} — ${item.name}`} closeLabel={t("action.close")} onClose={requestClose} wide footer={<>
      <span role="status" className={`text-editor-status ${error ? "error" : ""}`}>{error || (saving ? t("editor.saving") : dirty ? t("editor.unsaved") : readOnly ? t("editor.readOnly") : saved ? t("editor.saved") : t("status.ready"))}</span>
      {error && !version && <button type="button" onClick={() => void load()}>{t("action.retry")}</button>}
      <button type="button" disabled={saving} onClick={requestClose}>{t("action.close")}</button>
      <button className="button-primary" type="button" disabled={readOnly || !ready || saving || !dirty} onClick={() => void save()}><Save />{saving ? t("editor.saving") : t("action.save")}</button>
    </>}>
      <div className={`text-editor${readOnly ? " read-only" : ""}`}>
        <div className="text-editor-toolbar" role="toolbar" aria-label={t("editor.tools")}>
          <button type="button" disabled={!ready} onClick={() => { if (editorView.current) openSearchPanel(editorView.current); }}><Search />{t("editor.findReplace")}</button>
          <button type="button" disabled={!ready} onClick={() => { if (editorView.current) gotoLine(editorView.current); }}><ListOrdered />{t("editor.goToLine")}</button>
          <button type="button" disabled={!ready} aria-pressed={wrap} onClick={() => setWrap(!wrap)}><WrapText />{t("editor.wrap")}</button>
          <button type="button" disabled={loading || saving} onClick={requestReload}><RefreshCw />{t("editor.reload")}</button>
          <button type="button" disabled={!ready} onClick={downloadCopy}><Download />{t("editor.downloadCopy")}</button>
        </div>
        {lineEnding === "mixed" && <p className="text-editor-notice">{t("editor.mixedNotice")}</p>}
        <div className="text-editor-document">
          {loading ? <div className="loading-state">{t("status.loading")}</div> : error && !version ? <div className="error-state">{error}</div> : <div ref={editorHost} className="text-editor-codemirror" />}
        </div>
        <footer>
          <span>UTF-8</span>
          <label>{t("editor.lineEndings")}<select aria-label={t("editor.lineEndings")} value={lineEnding} disabled={!ready || readOnly} onChange={(event) => changeLineEnding(event.target.value as keyof typeof separators)}>
            {lineEnding === "mixed" && <option value="mixed" disabled>{t("editor.mixed")}</option>}
            <option value="LF">LF</option><option value="CRLF">CRLF</option><option value="CR">CR</option>
          </select></label>
          <span>{t("editor.position").replace("{line}", String(cursor.line)).replace("{column}", String(cursor.column))}</span>
          <span>{t("editor.lines").replace("{count}", String(lineCount))}</span>
          <span>{t("editor.characters").replace("{count}", String(value.length))}</span>
        </footer>
      </div>
    </Modal>
    {confirmation && <ConfirmDialog title={t(confirmation === "reload" ? "editor.reloadTitle" : "editor.closeTitle")} message={t(confirmation === "reload" ? "editor.reloadMessage" : "editor.closeMessage")} confirmLabel={t(confirmation === "reload" ? "editor.reload" : "editor.discard")} cancelLabel={t("action.cancel")} danger onClose={() => setConfirmation(null)} onConfirm={() => {
      const action = confirmation;
      setConfirmation(null);
      if (action === "reload") void load();
      else onClose();
    }} />}
  </>;
}
