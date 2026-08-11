import { HardDrive } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, logout, me, onAuthenticationInvalidated, type SettingsMe, type SettingsPatch, type Task, type UpdateCompletionNotice, type UpdateProgress, type UserPreferences } from "../api";
import { detectLanguage, type Language, translate } from "../i18n";
import type { Theme, Toast, User } from "./types";
import { Desktop } from "./Desktop";
import { ConnectionStatusMonitor } from "../features/connection/ConnectionStatusMonitor";
import { useUploadManager } from "../features/transfers/useUploadManager";
import { UpdateCompletionDialog, UpdateStatusPage } from "../features/settings/UpdateStatusPage";
import { Login } from "../features/auth/Login";

const COMPLETED_UPDATE_RELOAD_KEY = "webnas_completed_update_reload";
const reloadWindow = () => window.location.reload();

export function App({ reloadPage = reloadWindow }: { reloadPage?: () => void } = {}) {
  const [authStatus, setAuthStatus] = useState<"checking" | "authenticated" | "anonymous">("checking");
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

  const clearAuthenticatedUi = useCallback(() => {
    profileRef.current = null;
    setUser(null);
    setProfile(null);
    setTasks([]);
    setAuthStatus("anonymous");
  }, []);
  useEffect(() => {
    let active = true;
    const unsubscribe = onAuthenticationInvalidated(() => {
      if (active) clearAuthenticatedUi();
    });
    void me().then((restoredUser) => {
      if (!active) return;
      setUser(restoredUser);
      setAuthStatus("authenticated");
    }).catch(() => {
      if (active) clearAuthenticatedUi();
    });
    return () => { active = false; unsubscribe(); };
  }, [clearAuthenticatedUi]);
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
      setAuthStatus("checking");
      void me().then((restoredUser) => {
        setUser(restoredUser);
        setAuthStatus("authenticated");
      }).catch(clearAuthenticatedUi);
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
  }, [clearAuthenticatedUi, profile, refreshUpdateProgress, user]);
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
  }, [dismissedFailureId, updateProgress]);
  useEffect(() => {
    if (updateProgress?.state !== "completed" || window.location.pathname !== "/update-status") return;
    const updateId = updateProgress.id || updateProgress.commit_revision || String(updateProgress.finished_at || "completed");
    if (sessionStorage.getItem(COMPLETED_UPDATE_RELOAD_KEY) === updateId) return;
    sessionStorage.setItem(COMPLETED_UPDATE_RELOAD_KEY, updateId);
    window.history.replaceState({}, "", "/");
    reloadPage();
  }, [reloadPage, updateProgress]);
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
  if (authStatus === "checking") return <>{connectionStatus}<div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div></>;
  if (authStatus === "anonymous" || !user) return <>{connectionStatus}<Login language={language} onLogin={(authenticatedUser) => { setUser(authenticatedUser); setAuthStatus("authenticated"); }} /></>;
  if (!profile) return <>{connectionStatus}<div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div></>;
  if (!updateChecked) return <>{connectionStatus}<div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div></>;
  if (updateProgress && (
    ["waiting", "preparing", "running"].includes(updateProgress.state)
    || (updateProgress.state === "failed" && updateProgress.id !== dismissedFailureId)
    || (updateProgress.state === "completed" && window.location.pathname === "/update-status")
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
          clearAuthenticatedUi();
          window.history.replaceState({}, "", "/");
        });
      }}
    /></>;
  }
  return <>
    {connectionStatus}
    <Desktop user={user} profile={profile} language={language} theme={theme} tasks={[...tasks, ...uploads.tasks]} uploadControls={uploads.controls} toasts={toasts} t={t} toast={toast} onSettingsChange={updateSettings} onTheme={changeTheme} onLoggedOut={clearAuthenticatedUi} />
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
