import { KeyRound, LoaderCircle, Plus, Save, Trash2, UsersRound } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";

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

const roles: LocalRole[] = ["admin", "operator", "auditor", "user"];

export function AuthenticationSettingsControl({ active, locale, toast }: Props) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [settings, setSettings] = useState<AuthSettings | null>(null);
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [modeSaving, setModeSaving] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<LocalRole>("user");
  const [passwordDrafts, setPasswordDrafts] = useState<Record<string, string>>({});
  const pl = locale.toLowerCase().startsWith("pl");

  const copy = useMemo(() => pl ? {
    title: "Authentication",
    description: "Wybierz jeden globalny model logowania WebNAS. Domyślnie używana jest lokalna baza użytkowników aplikacji.",
    local: "Local database",
    localHint: "Logowanie wyłącznie kontami zapisanymi w lokalnej bazie WebNAS. PAM i LDAP nie są wtedy dostępne na ekranie logowania.",
    system: "PAM + LDAP",
    systemHint: "Logowanie kontami PAM. Po włączeniu LDAP użytkownik może wybrać LDAP lub PAM; LDAP jest wtedy domyślnie zaznaczony.",
    saveMode: "Zmień tryb",
    users: "Lokalni użytkownicy WebNAS",
    usersHint: "Hasła są przechowywane wyłącznie jako scrypt hash. Brak mapowania POSIX wyłącza operacje plikowe dla danego konta.",
    username: "Login",
    displayName: "Nazwa wyświetlana",
    password: "Hasło (min. 12 znaków)",
    role: "Rola",
    enabled: "Aktywne",
    posix: "POSIX",
    mapped: "mapped",
    notMapped: "brak",
    add: "Dodaj użytkownika",
    save: "Zapisz",
    remove: "Usuń",
    resetPassword: "Nowe hasło (opcjonalnie)",
    loadError: "Nie udało się odczytać ustawień authentication.",
    saved: "Ustawienia authentication zostały zapisane.",
    userSaved: "Użytkownik lokalny został zapisany.",
    userCreated: "Użytkownik lokalny został utworzony.",
    userDeleted: "Użytkownik lokalny został usunięty.",
    reauth: "Tryb logowania został zmieniony. Wymagane jest ponowne logowanie.",
  } : {
    title: "Authentication",
    description: "Choose one global WebNAS authentication model. The application-owned local user database is the default.",
    local: "Local database",
    localHint: "Only users stored in the WebNAS local database can sign in. PAM and LDAP are not available on the login page in this mode.",
    system: "PAM + LDAP",
    systemHint: "PAM login is available. When LDAP is enabled users can choose LDAP or PAM, with LDAP selected by default.",
    saveMode: "Change mode",
    users: "Local WebNAS users",
    usersHint: "Passwords are stored only as scrypt hashes. Without a POSIX mapping, file operations are disabled for that account.",
    username: "Username",
    displayName: "Display name",
    password: "Password (minimum 12 characters)",
    role: "Role",
    enabled: "Enabled",
    posix: "POSIX",
    mapped: "mapped",
    notMapped: "none",
    add: "Add user",
    save: "Save",
    remove: "Delete",
    resetPassword: "New password (optional)",
    loadError: "Could not load authentication settings.",
    saved: "Authentication settings were saved.",
    userSaved: "Local user was saved.",
    userCreated: "Local user was created.",
    userDeleted: "Local user was deleted.",
    reauth: "Authentication mode changed. Sign in again using the new mode.",
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

  async function createUser() {
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
      setNewUsername("");
      setNewDisplayName("");
      setNewPassword("");
      setNewRole("user");
      toast(copy.userCreated, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
    }
  }

  function patchUser(username: string, patch: Partial<LocalUser>) {
    setUsers((value) => value.map((user) => user.username === username ? { ...user, ...patch } : user));
  }

  async function saveUser(user: LocalUser) {
    const password = passwordDrafts[user.username] || undefined;
    try {
      const updated = await request<LocalUser>(`/api/settings/authentication/local-users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        body: JSON.stringify({
          role: user.role,
          enabled: user.enabled,
          display_name: user.display_name,
          ...(password ? { password } : {}),
        }),
      });
      patchUser(user.username, updated);
      setPasswordDrafts((value) => ({ ...value, [user.username]: "" }));
      toast(copy.userSaved, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
      void load();
    }
  }

  async function deleteUser(user: LocalUser) {
    try {
      await request(`/api/settings/authentication/local-users/${encodeURIComponent(user.username)}`, { method: "DELETE" });
      setUsers((value) => value.filter((item) => item.username !== user.username));
      toast(copy.userDeleted, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : copy.loadError, "error", "admin");
    }
  }

  const card = active && target ? createPortal(
    <div className="settings-card-stack" data-testid="authentication-settings-card">
      <section className="settings-card">
        <h3><KeyRound size={18} /> {copy.title}</h3>
        <p>{copy.description}</p>
        {loading && !settings ? <LoaderCircle className="spin" size={18} /> : settings && <>
          <div className="setting-row">
            <div><strong>{copy.local}</strong><small>{copy.localHint}</small></div>
            <div className="setting-control"><input type="radio" name="auth-mode" checked={settings.mode === "local"} disabled={modeSaving} onChange={() => void changeMode("local")} /></div>
          </div>
          <div className="setting-row">
            <div><strong>{copy.system}</strong><small>{copy.systemHint}</small></div>
            <div className="setting-control"><input type="radio" name="auth-mode" checked={settings.mode === "system"} disabled={modeSaving} onChange={() => void changeMode("system")} /></div>
          </div>
          {modeSaving && <p><LoaderCircle className="spin" size={16} /> {copy.saveMode}</p>}
        </>}
      </section>

      <section className="settings-card">
        <h3><UsersRound size={18} /> {copy.users}</h3>
        <p>{copy.usersHint}</p>
        <div className="setting-row"><div><strong>{copy.username}</strong></div><div className="setting-control"><input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} /></div></div>
        <div className="setting-row"><div><strong>{copy.displayName}</strong></div><div className="setting-control"><input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} /></div></div>
        <div className="setting-row"><div><strong>{copy.password}</strong></div><div className="setting-control"><input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></div></div>
        <div className="setting-row"><div><strong>{copy.role}</strong></div><div className="setting-control"><select value={newRole} onChange={(event) => setNewRole(event.target.value as LocalRole)}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></div></div>
        <div className="settings-actions"><button type="button" className="button-primary" disabled={!newUsername.trim() || newPassword.length < 12} onClick={() => void createUser()}><Plus size={16} />{copy.add}</button></div>

        {users.map((user) => <div className="settings-card" key={user.username}>
          <div className="setting-row"><div><strong>{user.username}</strong><small>{user.posix_mapped ? `${copy.posix}: ${copy.mapped}` : `${copy.posix}: ${copy.notMapped}`}</small></div><div className="setting-control"><input value={user.display_name} onChange={(event) => patchUser(user.username, { display_name: event.target.value })} /></div></div>
          <div className="setting-row"><div><strong>{copy.role}</strong></div><div className="setting-control"><select value={user.role} onChange={(event) => patchUser(user.username, { role: event.target.value as LocalRole })}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></div></div>
          <div className="setting-row"><div><strong>{copy.enabled}</strong></div><div className="setting-control"><input type="checkbox" checked={user.enabled} onChange={(event) => patchUser(user.username, { enabled: event.target.checked })} /></div></div>
          <div className="setting-row"><div><strong>{copy.resetPassword}</strong></div><div className="setting-control"><input type="password" autoComplete="new-password" value={passwordDrafts[user.username] || ""} onChange={(event) => setPasswordDrafts((value) => ({ ...value, [user.username]: event.target.value }))} /></div></div>
          <div className="settings-actions">
            <button type="button" className="button-primary" onClick={() => void saveUser(user)}><Save size={16} />{copy.save}</button>
            <button type="button" onClick={() => void deleteUser(user)}><Trash2 size={16} />{copy.remove}</button>
          </div>
        </div>)}
      </section>
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
