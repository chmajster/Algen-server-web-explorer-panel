import { HardDrive } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, login, logout, me, type SettingsMe, type SettingsPatch, type Task, type UpdateCompletionNotice, type UpdateProgress, type UserPreferences } from "../api";
import { detectLanguage, type Language, translate } from "../i18n";
import type { Theme, Toast, User } from "./types";
import { Desktop } from "./Desktop";
import { ConnectionStatusMonitor } from "../features/connection/ConnectionStatusMonitor";
import { useUploadManager } from "../features/transfers/useUploadManager";
import { UpdateCompletionDialog, UpdateStatusPage } from "../features/settings/UpdateStatusPage";

export function Login({ language, onLogin }: { language: Language; onLogin: (user: User) => void }) {
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [rememberMe, setRememberMe] = useState(false); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  const t = (key: string) => translate(language, key);
  async function submit(event: React.FormEvent) { event.preventDefault(); setLoading(true); setError(""); try { onLogin(await login(username.trim(), password, rememberMe)); } catch (reason) { setError(reason instanceof Error ? reason.message : t("auth.loginFailed")); } finally { setLoading(false); } }
  return <main className="login-screen"><form className="login-panel" onSubmit={submit}><div className="login-brand"><HardDrive /><div><strong>WebNAS</strong><span>{t("auth.subtitle")}</span></div></div><label>{t("auth.linuxUser")}<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label><label>{t("auth.password")}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><label className="remember-me-option"><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} /><span>{t("auth.rememberMe")}</span></label>{error && <p className="error-state">{error}</p>}<button className="button-primary" disabled={loading} type="submit">{loading ? t("status.loading") : t("auth.signIn")}</button></form></main>;
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<SettingsMe | null>(null);
  const [language, setLanguage] = useState<Language>(() => detectLanguage(localStorage.getItem("webnas_language")));
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("webnas_theme") as Theme) || "system");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [updateProgress, setUpdateProgress] = useState<UpdateProgress | null>(null);
  const [updateChecked, setUpdateChecked] = useState(false);
  const [updateConnectionError, setUpdateConnectionError] = useState(false);
  const [dismissedFailureId, setDismissedFailureId] = useState("");
  const [completionNotice, setCompletionNotice] = useState<UpdateCompletionNotice | null>(null);
  const profileRef = useRef<SettingsMe | null>(null);
  const settingsSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const settingsRevision = useRef(0);
  const settingRevisions = useRef<Partial<Record<keyof UserPreferences, number>>>({});
  const uploads = useUploadManager();
  const t = useCallback((key: string) => translate(language, key), [language]);
  const toast = useCallback((text: string, type: "ok" | "error" = "ok", category: "general" | "admin" | "transfer" = "general", moduleId?: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, text, type, category, moduleId }]);
    if (profileRef.current?.notification_auto_hide !== false) setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4200);
  }, []);

  useEffect(() => { me().then(setUser).catch(() => undefined); }, []);
  useEffect(() => {
    if (!user) { setProfile(null); return; }
    api.settingsMe().then((data) => { profileRef.current = data; setProfile(data); setLanguage(data.language); setTheme(data.theme); }).catch((error) => toast(error instanceof Error ? error.message : t("error.generic"), "error"));
  }, [t, toast, user]);
  useEffect(() => {
    if (!user || !profile) return;
    const refresh = () => (profile.permissions.includes("transfers.view_all") ? api.allTasks() : api.tasks()).then(setTasks).catch(() => undefined);
    void refresh(); const timer = setInterval(refresh, 1500); return () => clearInterval(timer);
  }, [profile, user]);
  const refreshUpdateProgress = useCallback(async (detailed = true) => {
    try {
      const value = await (detailed ? api.updateProgress() : api.updatePublicProgress());
      setUpdateProgress(value);
      setUpdateConnectionError(false);
      return value;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        profileRef.current = null;
        setUser(null);
        setProfile(null);
        setTasks([]);
      }
      setUpdateConnectionError(true);
      return null;
    } finally {
      setUpdateChecked(true);
    }
  }, []);
  const handleConnectionRestored = useCallback(() => {
    if (!user) {
      void me().then(setUser).catch(() => undefined);
      return;
    }
    if (!profile) return;
    void api.settingsMe().then((data) => {
      profileRef.current = data;
      setProfile(data);
      setLanguage(data.language);
      setTheme(data.theme);
    }).catch(() => undefined);
    void (profile.permissions.includes("transfers.view_all") ? api.allTasks() : api.tasks()).then(setTasks).catch(() => undefined);
    void refreshUpdateProgress(profile.permissions.includes("updates.view"));
  }, [profile, refreshUpdateProgress, user]);
  useEffect(() => {
    if (!user || !profile) {
      setUpdateChecked(false);
      setUpdateProgress(null);
      return;
    }
    const detailed = profile.permissions.includes("updates.view");
    void refreshUpdateProgress(detailed);
    const timer = window.setInterval(() => void refreshUpdateProgress(detailed), 1500);
    const refresh = () => void refreshUpdateProgress(detailed);
    window.addEventListener("webnas:update-status", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("webnas:update-status", refresh);
    };
  }, [profile, refreshUpdateProgress, user]);
  useEffect(() => {
    if (!updateProgress) return;
    const active = ["waiting", "preparing", "running"].includes(updateProgress.state);
    if (active && window.location.pathname !== "/update-status") {
      window.history.replaceState({}, "", "/update-status");
    }
    if (updateProgress.state === "failed" && updateProgress.id !== dismissedFailureId && window.location.pathname !== "/update-status") {
      window.history.replaceState({}, "", "/update-status");
    }
    if (updateProgress.state === "completed" && window.location.pathname === "/update-status") {
      window.history.replaceState({}, "", "/");
    }
  }, [dismissedFailureId, updateProgress]);
  useEffect(() => {
    if (!user || !profile?.permissions.includes("updates.view") || !updateChecked) return;
    if (updateProgress && ["waiting", "preparing", "running"].includes(updateProgress.state)) return;
    let live = true;
    void api.updateCompletion().then((value) => { if (live) setCompletionNotice(value.notice); }).catch(() => undefined);
    return () => { live = false; };
  }, [profile, updateChecked, updateProgress, user]);
  async function updateSettings(patch: SettingsPatch) {
    const currentProfile = profileRef.current || profile;
    if (!currentProfile) return;
    const previous = currentProfile;
    const revision = ++settingsRevision.current;
    const keys = Object.keys(patch) as Array<keyof UserPreferences>;
    keys.forEach((key) => { settingRevisions.current[key] = revision; });
    const optimistic = { ...currentProfile, ...patch };
    profileRef.current = optimistic;
    setProfile(optimistic);
    if (patch.language) setLanguage(patch.language);
    if (patch.theme) setTheme(patch.theme);
    try {
      const request = settingsSaveQueue.current.then(() => api.updateSettings(patch));
      settingsSaveQueue.current = request.then(() => undefined, () => undefined);
      const saved = await request;
      setProfile((current) => {
        if (!current) return current;
        const next = { ...current };
        keys.forEach((key) => { if (settingRevisions.current[key] === revision) Object.assign(next, { [key]: saved[key] }); });
        profileRef.current = next;
        return next;
      });
      if (patch.language && settingRevisions.current.language === revision) { setLanguage(saved.language); localStorage.setItem("webnas_language", saved.language); }
      if (patch.theme && settingRevisions.current.theme === revision) { setTheme(saved.theme); localStorage.setItem("webnas_theme", saved.theme); }
    } catch (error) {
      setProfile((current) => {
        if (!current) return current;
        const reverted = { ...current };
        keys.forEach((key) => {
          if (settingRevisions.current[key] === revision && current[key] === patch[key]) Object.assign(reverted, { [key]: previous[key] });
        });
        profileRef.current = reverted;
        return reverted;
      });
      if (patch.language && settingRevisions.current.language === revision) setLanguage(previous.language);
      if (patch.theme && settingRevisions.current.theme === revision) setTheme(previous.theme);
      throw error;
    }
  }
  function changeTheme(value: Theme) { void updateSettings({ theme: value }).catch((error) => toast(error instanceof Error ? error.message : t("error.generic"), "error")); }
  const connectionStatus = <ConnectionStatusMonitor t={t} language={language} onRestored={handleConnectionRestored} />;
  if (!user) return <>{connectionStatus}<Login language={language} onLogin={setUser} /></>;
  if (!profile) return <>{connectionStatus}<div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div></>;
  if (!updateChecked) return <>{connectionStatus}<div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div></>;
  if (updateProgress && (
    ["waiting", "preparing", "running"].includes(updateProgress.state)
    || (updateProgress.state === "failed" && updateProgress.id !== dismissedFailureId)
  )) {
    return <>{connectionStatus}<UpdateStatusPage
      value={updateProgress}
      connectionError={updateConnectionError}
      canRetry={profile.permissions.includes("updates.apply")}
      t={t}
      onRetry={() => {
        void api.runAutoUpdate(false).then((value) => { setDismissedFailureId(""); setUpdateProgress(value); }).catch(() => void refreshUpdateProgress());
      }}
      onReturn={() => {
        setDismissedFailureId(updateProgress.id || "latest");
        window.history.replaceState({}, "", "/");
      }}
      onLogin={() => {
        void logout().catch(() => undefined).finally(() => {
          profileRef.current = null;
          setUser(null);
          setProfile(null);
          setTasks([]);
          window.history.replaceState({}, "", "/");
        });
      }}
    /></>;
  }
  return <>
    {connectionStatus}
    <Desktop user={user} profile={profile} language={language} theme={theme} tasks={[...tasks, ...uploads.tasks]} uploadControls={uploads.controls} toasts={toasts} t={t} toast={toast} onSettingsChange={updateSettings} onTheme={changeTheme} onLoggedOut={() => { profileRef.current = null; setUser(null); setProfile(null); setTasks([]); }} />
    {completionNotice && <UpdateCompletionDialog
      notice={completionNotice}
      t={t}
      onClose={() => {
        const notice = completionNotice;
        setCompletionNotice(null);
        void api.acknowledgeUpdateCompletion(notice.id).catch(() => setCompletionNotice(notice));
      }}
    />}
  </>;
}
