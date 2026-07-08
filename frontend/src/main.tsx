import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Copy,
  Download,
  File,
  Folder,
  FolderPlus,
  Grid2X2,
  HardDrive,
  List,
  Lock,
  LogOut,
  Moon,
  RefreshCw,
  Search,
  Settings,
  Shield,
  Sun,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X
} from "lucide-react";
import { AdminGroup, AdminUser, api, downloadUrl, FileItem, login, logout, me, SettingsMe, Task } from "./api";
import { detectLanguage, Language, supportedLanguages, translate } from "./i18n";
import "./styles/app.css";

type User = { username: string; home: string };
type Toast = { id: number; text: string; type: "ok" | "error" };
type Theme = "light" | "dark" | "system";
type T = (key: string) => string;

function joinPath(base: string, name: string) {
  return `${base.replace(/\/$/, "")}/${name}`;
}

function formatSize(size: number) {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unit = units.shift() || "KB";
  while (value > 1024 && units.length) {
    value /= 1024;
    unit = units.shift() || unit;
  }
  return `${value.toFixed(value > 100 ? 0 : 1)} ${unit}`;
}

function message(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

function Login({ onLogin, t }: { onLogin: (user: User) => void; t: T }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      onLogin(await login(username, password));
    } catch (err) {
      setError(message(err, t("auth.loginFailed")));
    }
  }
  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <HardDrive size={34} />
        <h1>WebNAS</h1>
        <input autoFocus placeholder={t("auth.linuxUser")} value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder={t("auth.password")} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">{t("auth.signIn")}</button>
      </form>
    </main>
  );
}

function Window({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="window">
      <header className="window-title">
        <span>{title}</span>
        <div className="window-controls"><span /><span /><span /></div>
      </header>
      {children}
    </section>
  );
}

function Breadcrumbs({ path, onOpen }: { path: string; onOpen: (path: string) => void }) {
  const parts = path.split("/").filter(Boolean);
  const crumbs = parts.map((part, index) => ({ label: part, path: `/${parts.slice(0, index + 1).join("/")}` }));
  return (
    <nav className="breadcrumbs">
      <button onClick={() => onOpen("/")}>/</button>
      {crumbs.map((crumb) => (
        <button key={crumb.path} onClick={() => onOpen(crumb.path)}>{crumb.label}</button>
      ))}
    </nav>
  );
}

function Preview({ item, onClose, t }: { item: FileItem | null; onClose: () => void; t: T }) {
  const [content, setContent] = useState("");
  const [mime, setMime] = useState("");
  useEffect(() => {
    if (!item || item.is_dir) return;
    api.preview(item.path).then((data) => {
      setMime(data.mime);
      setContent(data.content_base64);
    });
  }, [item]);
  if (!item) return null;
  const src = `data:${mime};base64,${content}`;
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <header><strong>{item.name}</strong><button title={t("action.close")} onClick={onClose}><X size={16} /></button></header>
        {mime.startsWith("image/") ? <img className="preview-image" src={src} /> : <pre className="preview-text">{content ? atob(content) : ""}</pre>}
      </div>
    </div>
  );
}

function FileManager({ toast, t }: { toast: (text: string, type?: "ok" | "error") => void; t: T }) {
  const [path, setPath] = useState("");
  const [items, setItems] = useState<FileItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"list" | "grid">("list");
  const [query, setQuery] = useState("");
  const [clipboard, setClipboard] = useState<{ mode: "copy" | "move"; paths: string[] } | null>(null);
  const [preview, setPreview] = useState<FileItem | null>(null);

  async function load(next = path) {
    try {
      if (query) {
        const data = await api.search(next || path, query);
        setItems(data.items);
      } else {
        const data = await api.list(next);
        setPath(data.path);
        setItems(data.items);
      }
      setSelected(new Set());
    } catch (err) {
      toast(message(err, t("files.loadError")), "error");
    }
  }
  useEffect(() => { load(""); }, []);

  const selectedItems = useMemo(() => items.filter((item) => selected.has(item.path)), [items, selected]);
  function toggle(item: FileItem, multi: boolean) {
    setSelected((current) => {
      const next = multi ? new Set(current) : new Set<string>();
      next.has(item.path) ? next.delete(item.path) : next.add(item.path);
      return next;
    });
  }
  async function named(action: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      toast(action);
      await load();
    } catch (err) {
      toast(message(err, t("files.operationFailed")), "error");
    }
  }
  async function paste() {
    if (!clipboard) return;
    for (const src of clipboard.paths) {
      const name = src.split("/").pop() || "item";
      const dst = joinPath(path, name);
      await (clipboard.mode === "copy" ? api.copy(src, dst) : api.move(src, dst));
    }
    toast(t("files.taskQueued"));
    setClipboard(null);
  }
  return (
    <Window title={t("app.fileManager")}>
      <div className="toolbar">
        <button title={t("action.refresh")} onClick={() => load()}><RefreshCw size={17} /></button>
        <button title={t("action.newFolder")} onClick={() => { const name = prompt(t("files.folderName")); if (name) named(t("files.folderCreated"), () => api.mkdir(joinPath(path, name))); }}><FolderPlus size={17} /></button>
        <label className="icon-button" title={t("action.upload")}><Upload size={17} /><input type="file" multiple onChange={(e) => Array.from(e.target.files || []).forEach((file) => named(t("files.uploaded"), () => api.upload(path, file)))} /></label>
        <button title={t("action.copy")} disabled={!selected.size} onClick={() => setClipboard({ mode: "copy", paths: selectedItems.map((i) => i.path) })}><Copy size={17} /></button>
        <button title={t("action.paste")} disabled={!clipboard} onClick={paste}>{t("action.paste")}</button>
        <button title={t("action.delete")} disabled={!selected.size} onClick={() => selectedItems.forEach((item) => named(t("files.deleteQueued"), () => api.delete(item.path)))}><Trash2 size={17} /></button>
        <button title={t("action.listView")} onClick={() => setView("list")}><List size={17} /></button>
        <button title={t("action.gridView")} onClick={() => setView("grid")}><Grid2X2 size={17} /></button>
        <div className="search"><Search size={16} /><input placeholder={t("files.search")} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} /></div>
      </div>
      <Breadcrumbs path={path} onOpen={load} />
      <div className="file-layout">
        <aside>
          <button onClick={() => load(path)}><Folder size={16} /> {t("files.current")}</button>
          {items.filter((i) => i.is_dir).slice(0, 40).map((item) => <button key={item.path} onClick={() => load(item.path)}><Folder size={16} /> {item.name}</button>)}
        </aside>
        <main className={view === "grid" ? "grid-view" : "list-view"}>
          {items.map((item) => (
            <div
              key={item.path}
              className={`file-row ${selected.has(item.path) ? "selected" : ""}`}
              draggable
              onDragStart={() => setClipboard({ mode: "move", paths: [item.path] })}
              onDragOver={(e) => item.is_dir && e.preventDefault()}
              onDrop={() => item.is_dir && clipboard && api.move(clipboard.paths[0], joinPath(item.path, clipboard.paths[0].split("/").pop() || "item")).then(() => load())}
              onClick={(e) => toggle(item, e.ctrlKey || e.metaKey)}
              onDoubleClick={() => item.is_dir ? load(item.path) : setPreview(item)}
            >
              {item.is_dir ? <Folder size={22} /> : <File size={22} />}
              <span className="name">{item.name}</span>
              <span>{item.is_dir ? "" : formatSize(item.size)}</span>
              <span>{item.owner}:{item.group}</span>
              <span>{item.mode}</span>
              <div className="row-actions">
                {!item.is_dir && <a title={t("action.download")} href={downloadUrl(item.path)}><Download size={16} /></a>}
                <button title={t("action.rename")} onClick={(e) => { e.stopPropagation(); const name = prompt(t("files.newName"), item.name); if (name) named(t("files.renamed"), () => api.rename(item.path, joinPath(path, name))); }}>{t("action.rename")}</button>
              </div>
            </div>
          ))}
        </main>
      </div>
      <Preview item={preview} onClose={() => setPreview(null)} t={t} />
    </Window>
  );
}

function SettingsApp({ t, onLanguage, onTheme, toast }: { t: T; onLanguage: (language: Language) => void; onTheme: (theme: Theme) => void; toast: (text: string, type?: "ok" | "error") => void }) {
  const [tab, setTab] = useState("account");
  const [settings, setSettings] = useState<SettingsMe | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [groups, setGroups] = useState<AdminGroup[]>([]);
  const [system, setSystem] = useState<Record<string, unknown> | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});

  async function load() {
    const meData = await api.settingsMe();
    setSettings(meData);
    onLanguage(meData.language);
    onTheme(meData.theme);
    if (meData.is_admin) {
      api.adminUsers().then(setUsers).catch(() => undefined);
      api.adminGroups().then(setGroups).catch(() => undefined);
      api.systemStatus().then(setSystem).catch(() => undefined);
    }
  }
  useEffect(() => { load().catch((err) => toast(message(err, t("error.generic")), "error")); }, []);

  async function submit(okText: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      toast(okText);
      await load();
    } catch (err) {
      toast(message(err, t("error.generic")), "error");
    }
  }
  const adminPassword = () => form.admin_password || prompt(t("settings.adminPassword")) || "";

  return (
    <Window title={t("app.settings")}>
      <div className="settings-shell">
        <nav className="settings-tabs">
          {["account", "users", "groups", "permissions", "system"].map((item) => (
            <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{t(`settings.${item}`)}</button>
          ))}
        </nav>
        <main className="settings-panel">
          {tab === "account" && settings && (
            <section className="settings-section">
              <div className="form-grid">
                <label>{t("settings.language")}<select value={settings.language} onChange={(e) => submit(t("settings.saved"), async () => { const language = e.target.value as Language; await api.updateSettings({ language }); onLanguage(language); })}>{supportedLanguages.map((language) => <option key={language}>{language}</option>)}</select></label>
                <label>{t("settings.theme")}<select value={settings.theme} onChange={(e) => submit(t("settings.saved"), async () => { const theme = e.target.value as Theme; await api.updateSettings({ theme }); onTheme(theme); })}><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option><option value="system">{t("settings.systemTheme")}</option></select></label>
                <label>{t("settings.currentPassword")}<input type="password" onChange={(e) => setForm({ ...form, current_password: e.target.value })} /></label>
                <label>{t("settings.newPassword")}<input type="password" onChange={(e) => setForm({ ...form, new_password: e.target.value })} /></label>
              </div>
              <button onClick={() => submit(t("settings.passwordChanged"), () => api.changeMyPassword(form.current_password, form.new_password))}><Lock size={16} />{t("action.changePassword")}</button>
              <dl className="info-grid">
                <dt>{t("settings.username")}</dt><dd>{settings.username}</dd>
                <dt>{t("settings.uid")}</dt><dd>{settings.uid}</dd>
                <dt>{t("settings.gid")}</dt><dd>{settings.gid}</dd>
                <dt>{t("settings.groupsLabel")}</dt><dd>{settings.groups.join(", ")}</dd>
                <dt>{t("settings.home")}</dt><dd>{settings.home}</dd>
              </dl>
            </section>
          )}
          {tab === "users" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <div className="form-grid">
                  <input placeholder={t("settings.username")} onChange={(e) => setForm({ ...form, username: e.target.value })} />
                  <input type="password" placeholder={t("auth.password")} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                  <input placeholder={t("settings.shell")} onChange={(e) => setForm({ ...form, shell: e.target.value })} />
                  <input placeholder={t("settings.gecos")} onChange={(e) => setForm({ ...form, gecos: e.target.value })} />
                  <input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} />
                </div>
                <button onClick={() => submit(t("settings.addUser"), () => api.createUser({ username: form.username, password: form.password, shell: form.shell || undefined, gecos: form.gecos || undefined, create_home: true, admin_password: adminPassword() }))}><UserPlus size={16} />{t("settings.addUser")}</button>
                <h2>{t("settings.userList")}</h2>
                <div className="admin-list">{users.map((item) => <div key={item.username}><strong>{item.username}</strong><span>{item.uid}</span><span>{item.groups.join(", ")}</span><button onClick={() => submit(t("action.lock"), () => api.lockUser(item.username, adminPassword()))}>{t("action.lock")}</button><button onClick={() => submit(t("action.unlock"), () => api.unlockUser(item.username, adminPassword()))}>{t("action.unlock")}</button><button onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteUser(item.username, adminPassword()))}>{t("action.delete")}</button></div>)}</div>
              </>}
            </section>
          )}
          {tab === "groups" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && <>
                <div className="form-grid"><input placeholder={t("settings.groupName")} onChange={(e) => setForm({ ...form, groupname: e.target.value })} /><input placeholder={t("settings.member")} onChange={(e) => setForm({ ...form, member: e.target.value })} /><input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></div>
                <button onClick={() => submit(t("settings.addGroup"), () => api.createGroup({ groupname: form.groupname, admin_password: adminPassword() }))}><Users size={16} />{t("settings.addGroup")}</button>
                <h2>{t("settings.groupList")}</h2>
                <div className="admin-list">{groups.map((item) => <div key={item.name}><strong>{item.name}</strong><span>{item.gid}</span><span>{item.members.join(", ")}</span><button onClick={() => submit(t("action.add"), () => api.addGroupMember(item.name, { username: form.member, admin_password: adminPassword() }))}>{t("action.add")}</button><button onClick={() => submit(t("action.remove"), () => api.removeGroupMember(item.name, form.member, adminPassword()))}>{t("action.remove")}</button><button onClick={() => window.confirm(t("settings.confirmDelete")) && submit(t("action.delete"), () => api.deleteGroup(item.name, adminPassword()))}>{t("action.delete")}</button></div>)}</div>
              </>}
            </section>
          )}
          {tab === "permissions" && (
            <section className="settings-section">
              <div className="form-grid"><input placeholder={t("settings.filePath")} onChange={(e) => setForm({ ...form, perm_path: e.target.value })} /><input placeholder={t("settings.mode")} onChange={(e) => setForm({ ...form, mode: e.target.value })} /><input placeholder={t("settings.owner")} onChange={(e) => setForm({ ...form, owner: e.target.value })} /><input placeholder={t("settings.group")} onChange={(e) => setForm({ ...form, group: e.target.value })} /><input type="password" placeholder={t("settings.adminPassword")} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} /></div>
              <button onClick={() => submit(t("settings.applyChmod"), () => api.chmod(form.perm_path, form.mode))}><Shield size={16} />{t("settings.applyChmod")}</button>
              <button onClick={() => submit(t("settings.applyOwner"), () => api.chown({ path: form.perm_path, owner: form.owner || undefined, group: form.group || undefined, admin_password: adminPassword() }))}><Shield size={16} />{t("settings.applyOwner")}</button>
            </section>
          )}
          {tab === "system" && (
            <section className="settings-section">
              {!settings?.is_admin && <p className="error">{t("settings.adminOnly")}</p>}
              {settings?.is_admin && system && <>
                <dl className="info-grid">{Object.entries(system).map(([key, value]) => <React.Fragment key={key}><dt>{t(`settings.${key}`) || key}</dt><dd>{String(value)}</dd></React.Fragment>)}</dl>
                <button onClick={() => submit(t("action.restart"), () => api.restartSystem(adminPassword()))}><RefreshCw size={16} />{t("action.restart")}</button>
              </>}
            </section>
          )}
        </main>
      </div>
    </Window>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [language, setLanguage] = useState<Language>(() => detectLanguage(localStorage.getItem("webnas_language")));
  const [theme, setTheme] = useState<Theme>("system");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [activeApp, setActiveApp] = useState<"files" | "settings">("files");
  const t = (key: string) => translate(language, key);
  function toast(text: string, type: "ok" | "error" = "ok") {
    const id = Date.now();
    setToasts((items) => [...items, { id, text, type }]);
    setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4200);
  }
  function changeLanguage(next: Language) {
    setLanguage(next);
    localStorage.setItem("webnas_language", next);
  }
  useEffect(() => { me().then(setUser).catch(() => undefined); }, []);
  useEffect(() => {
    if (!user) return;
    api.settingsMe().then((data) => { changeLanguage(data.language); setTheme(data.theme); }).catch(() => undefined);
    const timer = setInterval(() => api.tasks().then(setTasks).catch(() => undefined), 1500);
    return () => clearInterval(timer);
  }, [user]);
  const resolvedTheme = theme === "system" && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : theme === "system" ? "dark" : theme;
  if (!user) return <Login onLogin={setUser} t={t} />;
  return (
    <div className={`app ${resolvedTheme}`}>
      <header className="topbar">
        <strong>WebNAS</strong>
        <span>{user.username}</span>
        <button title={t("notify.theme")} onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
        <button title={t("notify.logout")} onClick={() => logout().finally(() => setUser(null))}><LogOut size={17} /></button>
      </header>
      <div className="desktop-icons">
        <button onClick={() => setActiveApp("files")}><HardDrive size={28} /> {t("app.files")}</button>
        <button onClick={() => setActiveApp("settings")}><Settings size={28} /> {t("app.settings")}</button>
      </div>
      {activeApp === "files" ? <FileManager toast={toast} t={t} /> : <SettingsApp t={t} toast={toast} onLanguage={changeLanguage} onTheme={setTheme} />}
      <footer className="taskbar">
        <span>{activeApp === "files" ? t("app.fileManager") : t("app.settings")}</span>
        {tasks.slice(-3).map((task) => <span key={task.id} className={`task ${task.status}`}>{task.op}: {task.status} {task.progress}%</span>)}
      </footer>
      <div className="toasts">{toasts.map((item) => <div className={item.type} key={item.id}>{item.text}</div>)}</div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
