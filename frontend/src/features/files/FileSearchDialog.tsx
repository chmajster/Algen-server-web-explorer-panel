import { Copy, File, Folder, FolderOpen, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { api, type FileItem, type FileSearchOptions, type FileSearchResponse } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { formatSize } from "./utils";
import "./file-search-dialog.css";

export function FileSearchDialog({ path, initialQuery, showHidden, t, toast, onClose, onOpenItem, onOpenFolder }: {
  path: string;
  initialQuery: string;
  showHidden: boolean;
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onOpenItem: (item: FileItem) => void;
  onOpenFolder: (path: string) => void;
}) {
  const formId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [options, setOptions] = useState<FileSearchOptions>({ match_mode: "contains", item_type: "all", case_sensitive: false, show_hidden: showHidden });
  const [result, setResult] = useState<FileSearchResponse | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function search() {
    if (loading || !query.trim()) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError("");
    setResult(null);
    setSubmittedQuery(query.trim());
    try {
      const response = await api.search(path, query.trim(), options, request.signal);
      if (!request.signal.aborted) setResult(response);
    } catch (failure) {
      if (!request.signal.aborted) setError(failure instanceof Error ? failure.message : t("files.searchFailed"));
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  async function copyPath(value: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      toast(t("files.pathCopied"));
    } catch {
      toast(t("files.pathCopyFailed"), "error");
    }
  }

  return <Modal title={t("files.searchSubfolders")} onClose={onClose} wide className="file-search-dialog" footer={<>
    <button type="button" onClick={onClose}>{t("action.close")}</button>
    <button type="submit" form={formId} disabled={loading || !query.trim()}><Search aria-hidden="true" />{loading ? t("files.searching") : t("files.runSearch")}</button>
  </>}>
    <p className="file-search-scope">{t("files.searchScope")}<code>{path}</code></p>
    <form id={formId} className="file-search-form" onSubmit={(event) => { event.preventDefault(); void search(); }}>
      <label className="file-search-query">{t("files.searchName")}<input value={query} autoFocus required maxLength={256} onChange={(event) => setQuery(event.target.value)} /></label>
      <label>{t("files.searchMatchMode")}<select value={options.match_mode} onChange={(event) => setOptions((current) => ({ ...current, match_mode: event.target.value as FileSearchOptions["match_mode"] }))}>
        <option value="contains">{t("files.searchContains")}</option><option value="glob">{t("files.searchGlob")}</option>
      </select></label>
      <label>{t("files.searchType")}<select value={options.item_type} onChange={(event) => setOptions((current) => ({ ...current, item_type: event.target.value as FileSearchOptions["item_type"] }))}>
        <option value="all">{t("files.searchAllTypes")}</option><option value="files">{t("files.searchFilesOnly")}</option><option value="folders">{t("files.searchFoldersOnly")}</option>
      </select></label>
      <label className="file-search-toggle"><input type="checkbox" checked={options.case_sensitive} onChange={(event) => setOptions((current) => ({ ...current, case_sensitive: event.target.checked }))} />{t("files.searchCaseSensitive")}</label>
      <label className="file-search-toggle"><input type="checkbox" checked={options.show_hidden} onChange={(event) => setOptions((current) => ({ ...current, show_hidden: event.target.checked }))} />{t("files.searchHidden")}</label>
      {options.match_mode === "glob" && <p className="file-search-help">{t("files.searchGlobHint")}</p>}
    </form>
    {error && <p role="alert" className="file-search-error">{error}</p>}
    {loading && <p role="status">{t("files.searching")}</p>}
    {result && <div className="file-search-results">
      <p role="status">{t("files.searchResults").replace("{count}", String(result.items.length)).replace("{query}", submittedQuery)}</p>
      {result.truncated && <p className="file-search-warning" role="status">{t(`files.searchPartial.${result.reason || "limit"}`)}</p>}
      {!!result.skipped && <p className="file-search-warning">{t("files.searchSkipped").replace("{count}", String(result.skipped))}</p>}
      {result.items.length === 0 ? <p>{t("files.searchNoResults")}</p> : <ul>
        {result.items.map((item) => <li key={item.path}>
          <div className="file-search-result-details">
            <button className="file-search-result-name" onClick={() => onOpenItem(item)} aria-label={`${t("action.open")} ${item.name}`}>
              {item.is_dir ? <Folder aria-hidden="true" /> : <File aria-hidden="true" />}<strong>{item.name}</strong>
            </button>
            <code>{item.path}</code><small>{item.is_dir ? t("files.folder") : formatSize(item.size)}</small>
          </div>
          <div className="file-search-result-actions">
            <button title={t("files.openContainingFolder")} aria-label={`${t("files.openContainingFolder")} ${item.name}`} onClick={() => onOpenFolder(item.path.slice(0, item.path.lastIndexOf("/")) || "/")}><FolderOpen aria-hidden="true" /></button>
            <button title={t("files.copyPath")} aria-label={`${t("files.copyPath")} ${item.name}`} onClick={() => void copyPath(item.path)}><Copy aria-hidden="true" /></button>
          </div>
        </li>)}
      </ul>}
    </div>}
  </Modal>;
}
