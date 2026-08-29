import { HardDrive } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, logout, me, onAuthenticationInvalidated, type SettingsMe, type SettingsPatch, type Task, type UpdateCompletionNotice, type UpdateProgress, type UserPreferences } from "../api";
import { detectLanguage, type Language, translate } from "../i18n";
import { pageIsVisible, subscribePageVisibility } from "../core/runtime/pageVisibility";
import { runtimeConnectionState, subscribeRuntimeConnection, subscribeRuntimeEvent, type RuntimeConnectionState } from "../core/realtime/runtimeEvents";
import type { Theme, Toast, User } from "./types";
import { Desktop } from "./Desktop";
import { ConnectionStatusMonitor } from "../features/connection/ConnectionStatusMonitor";
import { useUploadManager } from "../features/transfers/useUploadManager";
import { UpdateCompletionDialog, UpdateStatusPage } from "../features/settings/UpdateStatusPage";
import { Login } from "../features/auth/Login";
import { DialogInfrastructure } from "../components/DialogService";

const COMPLETED_UPDATE_RELOAD_KEY = "webnas_completed_update_reload";
const TASK_FALLBACK_POLL_INTERVAL = 5000;
const UPDATE_ACTIVE_FALLBACK_POLL_INTERVAL = 1500;
const UPDATE_IDLE_FALLBACK_POLL_INTERVAL = 10000;
const reloadWindow = () => window.location.reload();

function sameStringArray(current: string[], next: string[]) {
  return current.length === next.length && current.every((value, index) => value === next[index]);
}

function sameTask(current: Task, next: Task) {
  return current.id === next.id
    && current.username === next.username
    && current.type === next.type
    && current.op === next.op
    && current.status === next.status
    && current.priority === next.priority
    && current.created_at === next.created_at
    && sameStringArray(current.source_paths, next.source_paths)
    && current.destination_path === next.destination_path
    && current.started_at === next.started_at
    && current.finished_at === next.finished_at
    && current.paused_at === next.paused_at
    && current.bytes_transferred === next.bytes_transferred
    && current.total_bytes === next.total_bytes
    && current.progress_percent === next.progress_percent
    && current.progress === next.progress
    && current.speed_bps === next.speed_bps
    && current.speed_human === next.speed_human
    && current.average_speed_bps === next.average_speed_bps
    && current.average_speed_human === next.average_speed_human
    && current.eta_seconds === next.eta_seconds
    && current.eta_human === next.eta_human
    && current.current_file === next.current_file
    && current.files_done === next.files_done
    && current.files_total === next.files_total
    && current.rsync_exit_code === next.rsync_exit_code
    && current.error_message === next.error_message
    && current.retry_count === next.retry_count
    && sameStringArray(current.errors, next.errors)
    && sameStringArray(current.log_tail, next.log_tail)
    && sameStringArray(current.stderr_tail, next.stderr_tail)
    && sameStringArray(current.command_preview, next.command_preview);
}

function sameTasks(current: Task[], next: Task[]) {
  return current.length === next.length && current.every((task, index) => sameTask(task, next[index]));
}

function updateStepSignature(value: UpdateProgress | null) {
  return (value?.steps || []).map((step) => `${step.id}:${step.status}:${step.message}:${step.finished_at ?? ""}`).join("|");
}

function blockerSignature(value: UpdateProgress | null) {
  return (value?.blockers || []).map((blocker) => `${blocker.id}:${blocker.status}:${blocker.progress ?? ""}`).join("|");
}

function sameUpdateProgress(current: UpdateProgress | null, next: UpdateProgress | null) {
  if (current === next) return true;
  if (!current || !next) return false;
  if (current.updated_at != null && next.updated_at != null && current.updated_at === next.updated_at && current.id === next.id) return true;
  return current.id === next.id
    && current.state === next.state
    && current.phase === next.phase
    && current.failed_phase === next.failed_phase
    && current.running === next.running
    && current.progress === next.progress
    && current.pid === next.pid
    && current.unit === next.unit
    && current.exit_code === next.exit_code
    && current.requested_at === next.requested_at
    && current.started_at === next.started_at
    && current.finished_at === next.finished_at
    && current.previous_version === next.previous_version
    && current.target_version === next.target_version
    && current.current_version === next.current_version
    && current.commit_revision === next.commit_revision
    && current.message === next.message
    && current.trigger === next.trigger
    && current.active_count === next.active_count
    && current.log === next.log
    && current.lines.length === next.lines.length
    && current.lines[current.lines.length - 1] === next.lines[next.lines.length - 1]
    && updateStepSignature(current) === updateStepSignature(next)
    && blockerSignature(current) === blockerSignature(next);
}

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
  const [runtimeState, setRuntimeState] = useState<RuntimeConnectionState>(() => runtimeConnectionState());
  const profileRef = useRef<SettingsMe | null>(null);
  const settingsSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const settingsRevision = useRef(0);
  const settingRevisions = useRef<Partial<Record<keyof UserPreferences, number>>>({});
  const uploads = useUploadManager();
  const mergedTasks = useMemo(() => [...tasks, ...uploads.tasks], [tasks, uploads.tasks]);
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

  useEffect(() => subscribeRuntimeConnection(() => setRuntimeState(runtimeConnectionState())), []);

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
    api.settingsMe().then((data) => {
      profileRef.current = data;
      setProfile(data);
      setLanguage(data.language);
      localStorage.setItem("webnas_language", data.language);
      setTheme(data.theme);
    }).catch((error) => toast(error instanceof Error ? error.message : t("error.generic"), "error"));
  }, [t, toast, user]);

  const refreshTasks = useCallback(() => {
    if (!user || !profile || !pageIsVisible()) return;
    void (profile.permissions.includes("transfers.view_all") ? api.allTasks() : api.tasks())
      .then((next) => setTasks((current) => sameTasks(current, next) ? current : next))
      .catch(() => undefined);
  }, [profile, user]);

  useEffect(() => {
    if (!user || !profile) return;
    refreshTasks();
    const unsubscribeEvent = subscribeRuntimeEvent("task.updated", refreshTasks);
    const unsubscribeVisibility = subscribePageVisibility((visible) => { if (visible) refreshTasks(); });
    return () => {
      unsubscribeEvent();
      unsubscribeVisibility();
    };
  }, [profile, refreshTasks, user]);

  useEffect(() => {
    if (!user || !profile || runtimeState !== "fallback") return;
    const timer = window.setInterval(refreshTasks, TASK_FALLBACK_POLL_INTERVAL);
    return () => window.clearInterval(timer);
  }, [profile, refreshTasks, runtimeState, user]);

  const refreshUpdateProgress = useCallback(async (detailed = true) => {
    try {
      const value = await (detailed ? api.updateProgress() : api.updatePublicProgress());
      setUpdateProgress((current) => sameUpdateProgress(current, value) ? current : value);
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
      localStorage.setItem("webnas_language", data.language);
      setTheme(data.theme);
    }).catch(() => undefined);
    refreshTasks();
    void refreshUpdateProgress(profile.permissions.includes("updates.view"));
  }, [clearAuthenticatedUi, profile, refreshTasks, refreshUpdateProgress, user]);
  useEffect(() => {
    if (!user || !profile) {
      setUpdateChecked(false);
      setUpdateProgress(null);
      return;
    }
    const detailed = profile.permissions.includes("updates.view");
    const refresh = () => { if (pageIsVisible()) void refreshUpdateProgress(detailed); };
    refresh();
    const unsubscribeEvent = subscribeRuntimeEvent("update.progress", refresh);
    const unsubscribeVisibility = subscribePageVisibility((visible) => { if (visible) refresh(); });
    window.addEventListener("webnas:update-status", refresh);
    return () => {
      unsubscribeEvent();
      unsubscribeVisibility();
      window.removeEventListener("webnas:update-status", refresh);
    };
  }, [profile, refreshUpdateProgress, user]);
  useEffect(() => {
    if (!user || !profile || runtimeState !== "fallback") return;
    const detailed = profile.permissions.includes("updates.view");
    const activeUpdate = Boolean(updateProgress && ["waiting", "preparing", "running"].includes(updateProgress.state));
    const interval = activeUpdate ? UPDATE_ACTIVE_FALLBACK_POLL_INTERVAL : UPDATE_IDLE_FALLBACK_POLL_INTERVAL;
    const timer = window.setInterval(() => { if (pageIsVisible()) void refreshUpdateProgress(detailed); }, interval);
    return () => window.clearInterval(timer);
  }, [profile, refreshUpdateProgress, runtimeState, updateProgress, user]);
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
    <Desktop user={user} profile={profile} language={language} theme={theme} tasks={mergedTasks} uploadControls={uploads.controls} toasts={toasts} t={t} toast={toast} onSettingsChange={updateSettings} onTheme={changeTheme} onLoggedOut={clearAuthenticatedUi} />
    <DialogInfrastructure />
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
