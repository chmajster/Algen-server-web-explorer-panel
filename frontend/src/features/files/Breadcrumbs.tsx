import { Check, Clipboard, Edit3, X } from "lucide-react";
import { useState } from "react";
import type { Translate } from "../../app/types";

export function Breadcrumbs({ path, t, onOpen }: { path: string; t: Translate; onOpen: (path: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(path);
  const parts = path.split("/").filter(Boolean);
  return <nav className="breadcrumbs" aria-label={t("files.path")}>
    {editing ? <form onSubmit={(event) => { event.preventDefault(); onOpen(value || "/"); setEditing(false); }}>
      <input value={value} onChange={(event) => setValue(event.target.value)} aria-label={t("files.fullPath")} autoFocus />
      <button type="submit" title={t("action.apply")}><Check /></button><button type="button" title={t("action.cancel")} onClick={() => setEditing(false)}><X /></button>
    </form> : <div className="crumb-list"><button type="button" onClick={() => onOpen("/")}>/</button>{parts.map((part, index) => { const target = `/${parts.slice(0, index + 1).join("/")}`; return <button type="button" key={target} onClick={() => onOpen(target)}>{part}</button>; })}</div>}
    <div className="breadcrumb-actions"><button type="button" title={t("files.editPath")} onClick={() => { setValue(path); setEditing(true); }}><Edit3 /></button><button type="button" title={t("files.copyPath")} onClick={() => navigator.clipboard?.writeText(path)}><Clipboard /></button></div>
  </nav>;
}
