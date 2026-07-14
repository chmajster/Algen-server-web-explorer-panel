import { useState } from "react";
import { api, type FileItem } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { formatDate, formatSize, joinPath } from "./utils";

export function FileProperties({ item, currentPath, isAdmin, sambaShared, t, toast, onClose, onChanged }: {
  item: FileItem;
  currentPath: string;
  isAdmin: boolean;
  sambaShared: boolean;
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState(item.name);
  const [owner, setOwner] = useState(item.owner);
  const [group, setGroup] = useState(item.group);
  const [mode, setMode] = useState(item.mode || item.permissions);
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    try {
      const effectivePath = name !== item.name ? joinPath(currentPath, name) : item.path;
      if (name !== item.name) await api.rename(item.path, effectivePath);
      if (isAdmin && (owner !== item.owner || group !== item.group)) await api.chown({ path: effectivePath, owner, group, admin_password: password });
      if (isAdmin && mode !== (item.mode || item.permissions)) await api.chmod(effectivePath, mode);
      toast(t("files.propertiesSaved")); onChanged(); onClose();
    } catch (error) { toast(error instanceof Error ? error.message : t("files.operationFailed"), "error"); }
    finally { setSaving(false); }
  }
  return <Modal title={t("files.properties")} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button>{isAdmin && <button className="button-primary" disabled={saving} onClick={() => void save()}>{t("action.save")}</button>}</>}>
    <dl className="properties-grid">
      <dt>{t("column.name")}</dt><dd>{isAdmin ? <input value={name} onChange={(event) => setName(event.target.value)} /> : item.name}</dd>
      <dt>{t("files.fullPath")}</dt><dd><code>{item.path}</code></dd>
      <dt>{t("column.type")}</dt><dd>{item.type}</dd>
      <dt>{t("column.size")}</dt><dd>{item.is_dir ? "—" : formatSize(item.size)}</dd>
      <dt>{t("column.owner")}</dt><dd>{isAdmin ? <input value={owner} onChange={(event) => setOwner(event.target.value)} /> : item.owner}</dd>
      <dt>{t("column.group")}</dt><dd>{isAdmin ? <input value={group} onChange={(event) => setGroup(event.target.value)} /> : item.group}</dd>
      <dt>{t("column.permissions")}</dt><dd>{isAdmin ? <input value={mode} onChange={(event) => setMode(event.target.value)} /> : item.permissions}</dd>
      <dt>{t("column.modified")}</dt><dd>{formatDate(item.mtime || item.modified)}</dd>
      <dt>{t("files.symlink")}</dt><dd>{item.is_symlink ? item.target || t("common.yes") : t("common.no")}</dd>
      <dt>{t("files.mountPoint")}</dt><dd>{item.is_dir ? item.path : "—"}</dd>
      <dt>{t("files.sambaShared")}</dt><dd>{sambaShared ? t("common.yes") : t("common.no")}</dd>
    </dl>
    {isAdmin && <label className="field-label">{t("settings.adminPassword")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>}
  </Modal>;
}
