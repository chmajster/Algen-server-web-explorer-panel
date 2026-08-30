import { Check, Edit3, KeyRound, LoaderCircle, Plus, Save, ShieldCheck, Trash2, UserRound, UsersRound, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";
import "../../styles/authentication-settings.css";

type AuthMode = "local" | "system";
type LocalRole = "admin" | "operator" | "auditor" | "user";

type AuthSettings = {
  mode: AuthMode;
  default_mode: "local";
  local_database_enabled: boolean;
  system_authentication_enabled: boolean;
  local_user_count: number;
  local_enabled_admin_count: number;
  reauthentication_required?: boolean;
};

type LocalUser = {
  username: string;
  role: LocalRole;
  enabled: boolean;
  display_name: string;
  home: string;
  posix_mapped: boolean;
  created_at: number;
  updated_at: number;
  last_login_at: number;
  password_changed_at: number;
};

type Props = {
  active: boolean;
  locale: string;
  toast: ToastFn;
};

type UserDialogState =
  | { mode: "create" }
  | { mode: "edit"; username: string }
  | null;

const roles: LocalRole[] = ["admin", "operator", "auditor", "user"];

export function AuthenticationSettingsControl({ active, locale, toast }: Props) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [settings, setSettings] = useState<AuthSettings | null>(null);
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [modeSaving, setModeSaving] = useState(false);
  const [userSaving, setUserSaving] = useState(false);
  const [dialog, setDialog] = useState<UserDialogState>(null);
  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<LocalRole>("user");
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [editRole, setEditRole] = useState<LocalRole>("user");
  const [editEnabled, setEditEnabled] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const pl = locale.toLowerCase().startsWith("pl");

  const copy = useMemo(() => pl ? {
    title: "Metoda uwierzytelniania",
    description: "Wybierz globalny model logowania do WebNAS.",
    local: "Local database",
    localHint: "Konta przechowywane lokalnie w WebNAS.",
    system: "PAM + LDAP",
    systemHint: "Konta systemowe PAM oraz katalog LDAP.",
    changing: "Zmiana trybu…",
    users: "Lokalni użytkownicy WebNAS",
    usersHint: "Konta awaryjne i lokalne zarządzane przez WebNAS. Brak mapowania POSIX blokuje operacje plikowe.",
    username: "Login",
    displayName: "Nazwa wyświetlana",
    password: "Hasło",
    passwordHint: "Minimum 12 znaków",
    role: "Rola",
    enabled: "Konto aktywne",
    posix: "POSIX",
    mapped: "Mapped",
    notMapped: "Not mapped",
    status: "Status",
    active: "Active",
    disabled: "Disabled",
    actions: "Akcje",
    add: "Dodaj użytkownika",
    addTitle: "Dodaj lokalnego użytkownika",
    editTitle: "Edytuj lokalnego użytkownika",
    save: "Zapisz zmiany",
    remove: "Usuń użytkownika",
    cancel: "Anuluj",
    resetPassword: "Nowe hasło (opcjonalnie)",
    deleteQuestion: "Usunąć tego użytkownika?",
    deleteHint: "Operacja usuwa konto z lokalnej bazy WebNAS i nie może zostać cofnięta.",
    confirmDelete: "Tak, usuń",
    loadError: "Nie udało się odczytać ustawień authentication.",
    saved: "Ustawienia authentication zostały zapisane.",
    userSaved: "Użytkownik lokalny został zapisany.",
    userCreated: "Użytkownik lokalny został utworzony.",
    userDeleted: "Użytkownik lokalny został usunięty.",
    reauth: "Tryb logowania został zmieniony. Wymagane jest ponowne logowanie.",
    empty: "Brak lokalnych użytkowników.",
  } : {
    title: "Authentication method",
    description: "Choose the global WebNAS sign-in model.",
    local: "Local database",
    localHint: "Accounts stored locally in WebNAS.",
    system: "PAM + LDAP",
    systemHint: "System PAM accounts and the LDAP directory.",
    changing: "Changing mode…",
    users: "Local WebNAS users",
    usersHint: "Emergency and local accounts managed by WebNAS. Without POSIX mapping, file operations are disabled.",
    username: "Username",
    displayName: "Display name",
    password: "Password",
    passwordHint: "Minimum 12 characters",
    role: "Role",
    enabled: "Account enabled",
    posix: "POSIX",
    mapped: "Mapped",
    notMapped: "Not mapped",
    status: "Status",
    active: "Active",
    disabled: "Disabled",
    actions: "Actions",
    add: "Add user",
    addTitle: "Add local user",
    editTitle: "Edit local user",
    save: "Save changes",
    remove: "Delete user",
    cancel: "Cancel",
    resetPassword: "New password (optional)",
    deleteQuestion: "Delete this user?",
    deleteHint: "This removes the account from the WebNAS local database and cannot be undone.",
    confirmDelete: "Yes, delete",
    loadError: "Could not load authentication settings.",
    saved: "Authentication settings were saved.",
    userSaved: "Local user was saved.",
    userCreated: "Local user was created.",
    userDeleted: "Local user was deleted.",
    reauth: "Authentication mode changed. Sign in again using the new mode.",
    empty: "No local users.",
  }, [pl]);

  useEffect(() => {
    if (!active) { setTarget(null); return; }
    const root = anchorRef.current?.parentElement;
    const resolve = () => setTarget(root?.querySelector(".settings-content") || null);
    resolve();
    if (!root) return;
    const observer = new MutationObserver(resolve);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [active]);

  useEffect(() => {
    if (!dialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDialog();
    };
    document.addEventListener("keydown", onKeyDown);
    window.setTimeout(() => dialogRef.current?.querySelector<HTMLElement>("input, select, button")?.focus(), 0);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dialog]);

  async function load() {
    setLoading(true);
    try {
      const [nextSettings, localUsers] = await Promise.all([
        request<AuthSettings>("/api/settings/authentication"),
        request<{ users: LocalUser[] }>("/api/settings/authentication/local-users"),
      ]);
      setSettings(nextSettings);
      setUsers(localUsers.users);
    } catch {
      toast(copy.loadError, "error", "admin");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (active) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function changeMode(mode: AuthMode) {
    if (!settings || mode === settings.mode) return;
    setModeSaving(true);
    try {
      const result = await request<AuthSettings>("/api/settings/authentication", {
        method: "PUT",
        body: JSON.stringify({ mode }),
      });
      setSettings(result);
      toast(result.reauthentication_required ? copy.reauth : copy.saved, "ok", "admin");
      if (result.reauthentication_required) window.setTimeout(() => window.location.reload(), 350);
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
    } finally {
      setModeSaving(false);
    }
  }

  function resetCreateForm() {
    setNewUsername("");
    setNewDisplayName("");
    setNewPassword("");
    setNewRole("user");
  }

  function closeDialog() {
    setDialog(null);
    setDeleteConfirm(false);
    setEditPassword("");
  }

  function openCreateDialog() {
    resetCreateForm();
    setDeleteConfirm(false);
    setDialog({ mode: "create" });
  }

  function openEditDialog(user: LocalUser) {
    setEditDisplayName(user.display_name);
    setEditRole(user.role);
    setEditEnabled(user.enabled);
    setEditPassword("");
    setDeleteConfirm(false);
    setDialog({ mode: "edit", username: user.username });
  }

  async function createUser() {
    setUserSaving(true);
    try {
      const created = await request<LocalUser>("/api/settings/authentication/local-users", {
        method: "POST",
        body: JSON.stringify({
          username: newUsername.trim(),
          display_name: newDisplayName.trim(),
          password: newPassword,
          role: newRole,
        }),
      });
      setUsers((value) => [...value, created].sort((a, b) => a.username.localeCompare(b.username)));
      resetCreateForm();
      closeDialog();
      toast(copy.userCreated, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
    } finally {
      setUserSaving(false);
    }
  }

  async function saveUser(user: LocalUser) {
    setUserSaving(true);
    try {
      const updated = await request<LocalUser>(`/api/settings/authentication/local-users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        body: JSON.stringify({
          role: editRole,
          enabled: editEnabled,
          display_name: editDisplayName,
          ...(editPassword ? { password: editPassword } : {}),
        }),
      });
      setUsers((value) => value.map((item) => item.username === user.username ? updated : item));
      closeDialog();
      toast(copy.userSaved, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
      void load();
    } finally {
      setUserSaving(false);
    }
  }

  async function deleteUser(user: LocalUser) {
    setUserSaving(true);
    try {
      await request(`/api/settings/authentication/local-users/${encodeURIComponent(user.username)}`, { method: "DELETE" });
      setUsers((value) => value.filter((item) => item.username !== user.username));
      closeDialog();
      toast(copy.userDeleted, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
    } finally {
      setUserSaving(false);
    }
  }

  const editingUser = dialog?.mode === "edit" ? users.find((user) => user.username === dialog.username) || null : null;

  const dialogContent = dialog ? <div className="auth-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog(); }}>
    <div ref={dialogRef} className="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="local-user-dialog-title">
      <div className="auth-dialog__header">
        <div>
          <h3 id="local-user-dialog-title">{dialog.mode === "create" ? copy.addTitle : copy.editTitle}</h3>
          {editingUser && <p>{editingUser.username}</p>}
        </div>
        <button type="button" className="auth-icon-button" aria-label={copy.cancel} onClick={closeDialog}><X size={17} /></button>
      </div>

      {dialog.mode === "create" ? <div className="auth-dialog__body auth-form-grid">
        <label className="auth-field"><span>{copy.username}</span><input autoComplete="username" value={newUsername} onChange={(event) => setNewUsername(event.target.value)} /></label>
        <label className="auth-field"><span>{copy.displayName}</span><input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} /></label>
        <label className="auth-field auth-field--wide"><span>{copy.password}</span><input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /><small>{copy.passwordHint}</small></label>
        <label className="auth-field"><span>{copy.role}</span><select value={newRole} onChange={(event) => setNewRole(event.target.value as LocalRole)}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
      </div> : editingUser && <div className="auth-dialog__body auth-form-grid">
        <div className="auth-field"><span>{copy.username}</span><div className="auth-static-value">{editingUser.username}</div></div>
        <label className="auth-field"><span>{copy.displayName}</span><input value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} /></label>
        <label className="auth-field"><span>{copy.role}</span><select value={editRole} onChange={(event) => setEditRole(event.target.value as LocalRole)}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
        <label className="auth-field auth-field--switch"><span>{copy.enabled}</span><span className="settings-switch"><input type="checkbox" checked={editEnabled} onChange={(event) => setEditEnabled(event.target.checked)} /><span aria-hidden="true" /></span></label>
        <div className="auth-field"><span>{copy.posix}</span><div><span className={`auth-badge ${editingUser.posix_mapped ? "auth-badge--ok" : "auth-badge--muted"}`}>{editingUser.posix_mapped ? copy.mapped : copy.notMapped}</span></div></div>
        <label className="auth-field auth-field--wide"><span>{copy.resetPassword}</span><input type="password" autoComplete="new-password" value={editPassword} onChange={(event) => setEditPassword(event.target.value)} /><small>{copy.passwordHint}</small></label>
        {deleteConfirm && <div className="auth-delete-confirm auth-field--wide"><strong>{copy.deleteQuestion}</strong><span>{copy.deleteHint}</span></div>}
      </div>}

      <div className="auth-dialog__footer">
        {dialog.mode === "edit" && editingUser ? <div className="auth-dialog__danger">
          {!deleteConfirm ? <button type="button" className="auth-danger-button" disabled={userSaving} onClick={() => setDeleteConfirm(true)}><Trash2 size={15} />{copy.remove}</button> : <button type="button" className="auth-danger-button auth-danger-button--confirm" disabled={userSaving} onClick={() => void deleteUser(editingUser)}>{copy.confirmDelete}</button>}
        </div> : <span />}
        <div className="auth-dialog__actions">
          <button type="button" disabled={userSaving} onClick={closeDialog}>{copy.cancel}</button>
          {dialog.mode === "create" ? <button type="button" className="button-primary" disabled={userSaving || !newUsername.trim() || newPassword.length < 12} onClick={() => void createUser()}>{userSaving ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{copy.add}</button> : editingUser && <button type="button" className="button-primary" disabled={userSaving || Boolean(editPassword && editPassword.length < 12)} onClick={() => void saveUser(editingUser)}>{userSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{copy.save}</button>}
        </div>
      </div>
    </div>
  </div> : null;

  const card = active && target ? createPortal(
    <div className="auth-settings-shell" data-testid="authentication-settings-card">
      <section className="auth-panel auth-mode-panel">
        <div className="auth-panel__heading">
          <div>
            <h3><KeyRound size={18} /> {copy.title}</h3>
            <p>{copy.description}</p>
          </div>
          {modeSaving && <span className="auth-inline-status"><LoaderCircle className="spin" size={15} /> {copy.changing}</span>}
        </div>
        {loading && !settings ? <div className="auth-loading"><LoaderCircle className="spin" size={18} /></div> : settings && <div className="auth-mode-grid" role="radiogroup" aria-label={copy.title}>
          <button type="button" role="radio" aria-checked={settings.mode === "local"} className={`auth-mode-card ${settings.mode === "local" ? "is-selected" : ""}`} disabled={modeSaving} onClick={() => void changeMode("local")}>
            <span className="auth-mode-card__icon"><UserRound size={19} /></span>
            <span className="auth-mode-card__content"><strong>{copy.local}</strong><small>{copy.localHint}</small></span>
            <span className="auth-mode-card__check" aria-hidden="true">{settings.mode === "local" && <Check size={16} />}</span>
          </button>
          <button type="button" role="radio" aria-checked={settings.mode === "system"} className={`auth-mode-card ${settings.mode === "system" ? "is-selected" : ""}`} disabled={modeSaving} onClick={() => void changeMode("system")}>
            <span className="auth-mode-card__icon"><ShieldCheck size={19} /></span>
            <span className="auth-mode-card__content"><strong>{copy.system}</strong><small>{copy.systemHint}</small></span>
            <span className="auth-mode-card__check" aria-hidden="true">{settings.mode === "system" && <Check size={16} />}</span>
          </button>
        </div>}
      </section>

      <section className="auth-panel auth-users-panel">
        <div className="auth-panel__heading auth-panel__heading--actions">
          <div>
            <h3><UsersRound size={18} /> {copy.users}</h3>
            <p>{copy.usersHint}</p>
          </div>
          <button type="button" className="button-primary" onClick={openCreateDialog}><Plus size={16} />{copy.add}</button>
        </div>

        <div className="auth-users-table-wrap">
          <table className="auth-users-table">
            <thead><tr><th>{copy.username}</th><th>{copy.displayName}</th><th>{copy.role}</th><th>{copy.posix}</th><th>{copy.status}</th><th className="auth-users-table__actions">{copy.actions}</th></tr></thead>
            <tbody>
              {users.map((user) => <tr key={user.username} onDoubleClick={() => openEditDialog(user)}>
                <td data-label={copy.username}><strong>{user.username}</strong></td>
                <td data-label={copy.displayName}>{user.display_name || "—"}</td>
                <td data-label={copy.role}><span className="auth-badge auth-badge--role">{user.role}</span></td>
                <td data-label={copy.posix}><span className={`auth-badge ${user.posix_mapped ? "auth-badge--ok" : "auth-badge--muted"}`}>{user.posix_mapped ? copy.mapped : copy.notMapped}</span></td>
                <td data-label={copy.status}><span className={`auth-badge ${user.enabled ? "auth-badge--ok" : "auth-badge--muted"}`}>{user.enabled ? copy.active : copy.disabled}</span></td>
                <td className="auth-users-table__actions"><button type="button" className="auth-icon-button" aria-label={`${copy.editTitle}: ${user.username}`} onClick={() => openEditDialog(user)}><Edit3 size={16} /></button></td>
              </tr>)}
              {!users.length && !loading && <tr><td colSpan={6} className="auth-empty-state">{copy.empty}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {dialogContent}
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
