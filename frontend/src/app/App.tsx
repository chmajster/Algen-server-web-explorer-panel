import { HardDrive } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, login, me, type SettingsMe, type Task } from "../api";
import { detectLanguage, type Language, translate } from "../i18n";
import type { Theme, Toast, User } from "./types";
import { Desktop } from "./Desktop";

function Login({ language, onLogin }: { language: Language; onLogin: (user: User) => void }) {
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  const t = (key: string) => translate(language, key);
  async function submit(event: React.FormEvent) { event.preventDefault(); setLoading(true); setError(""); try { onLogin(await login(username.trim(), password)); } catch (reason) { setError(reason instanceof Error ? reason.message : t("auth.loginFailed")); } finally { setLoading(false); } }
  return <main className="login-screen"><form className="login-panel" onSubmit={submit}><div className="login-brand"><HardDrive /><div><strong>WebNAS</strong><span>{t("auth.subtitle")}</span></div></div><label>{t("auth.linuxUser")}<input autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label><label>{t("auth.password")}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="error-state">{error}</p>}<button className="button-primary" disabled={loading} type="submit">{loading ? t("status.loading") : t("auth.signIn")}</button></form></main>;
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<SettingsMe | null>(null);
  const [language, setLanguage] = useState<Language>(() => detectLanguage(localStorage.getItem("webnas_language")));
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("webnas_theme") as Theme) || "system");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const t = useCallback((key: string) => translate(language, key), [language]);
  const toast = useCallback((text: string, type: "ok" | "error" = "ok") => { const id = Date.now() + Math.random(); setToasts((current) => [...current, { id, text, type }]); setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 4200); }, []);

  useEffect(() => { me().then(setUser).catch(() => undefined); }, []);
  useEffect(() => {
    if (!user) { setProfile(null); return; }
    api.settingsMe().then((data) => { setProfile(data); setLanguage(data.language); setTheme(data.theme); }).catch((error) => toast(error instanceof Error ? error.message : t("error.generic"), "error"));
    const refresh = () => api.tasks().then(setTasks).catch(() => undefined);
    void refresh(); const timer = setInterval(refresh, 1500); return () => clearInterval(timer);
  }, [t, toast, user]);
  function changeLanguage(value: Language) { setLanguage(value); localStorage.setItem("webnas_language", value); api.updateSettings({ language: value }).catch(() => undefined); }
  function changeTheme(value: Theme) { setTheme(value); localStorage.setItem("webnas_theme", value); api.updateSettings({ theme: value }).catch(() => undefined); }
  if (!user) return <Login language={language} onLogin={setUser} />;
  if (!profile) return <div className="boot-screen"><HardDrive className="pulse" /><span>{t("status.loading")}</span></div>;
  return <Desktop user={user} profile={profile} language={language} theme={theme} tasks={tasks} toasts={toasts} t={t} toast={toast} onLanguage={changeLanguage} onTheme={changeTheme} onLoggedOut={() => { setUser(null); setProfile(null); setTasks([]); }} />;
}
