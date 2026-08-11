import { CircleAlert, Eye, EyeOff, HardDrive, LoaderCircle, LockKeyhole, UserRound } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { login } from "../../api";
import { translate, type Language } from "../../i18n";
import type { User } from "../../app/types";

function authenticationError(reason: unknown, t: (key: string) => string) {
  const status = reason && typeof reason === "object" && "status" in reason ? Number(reason.status) : 0;
  if (status === 400 || status === 401) return t("auth.invalidCredentials");
  if (reason instanceof Error && /^invalid username(?: or password)?$/i.test(reason.message.trim())) return t("auth.invalidCredentials");
  return reason instanceof Error ? reason.message : t("auth.loginFailed");
}

export function Login({ language, onLogin }: { language: Language; onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submitting = useRef(false);
  const t = (key: string) => translate(language, key);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setLoading(true);
    setError("");
    const finish = () => { submitting.current = false; setLoading(false); };
    try {
      void Promise.resolve(login(username.trim(), password, rememberMe))
        .then(onLogin)
        .catch((reason: unknown) => setError(authenticationError(reason, t)))
        .finally(finish)
        .catch(() => { setError(t("auth.loginFailed")); finish(); });
    } catch (reason) {
      setError(authenticationError(reason, t));
      finish();
    }
  }

  return <main className="login-screen">
    <form className="login-panel" onSubmit={submit} aria-busy={loading}>
      <header className="login-brand"><span className="login-brand-icon"><HardDrive aria-hidden="true" /></span><div><h1>WebNAS</h1><p>{t("auth.subtitle")}</p></div></header>
      <div className="login-fields">
        <label className="login-field"><span>{t("auth.linuxUser")}</span><span className="login-input"><UserRound aria-hidden="true" /><input autoFocus required autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="username" value={username} aria-invalid={Boolean(error)} aria-describedby={error ? "login-error" : undefined} onChange={(event) => setUsername(event.target.value)} /></span></label>
        <label className="login-field"><span>{t("auth.password")}</span><span className="login-input"><LockKeyhole aria-hidden="true" /><input required type={passwordVisible ? "text" : "password"} autoComplete="current-password" value={password} aria-invalid={Boolean(error)} aria-describedby={error ? "login-error" : undefined} onChange={(event) => setPassword(event.target.value)} /><button type="button" className="login-password-toggle" aria-label={t(passwordVisible ? "auth.hidePassword" : "auth.showPassword")} aria-pressed={passwordVisible} onClick={() => setPasswordVisible((visible) => !visible)}>{passwordVisible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}</button></span></label>
      </div>
      {error && <div id="login-error" className="login-error" role="alert" aria-live="polite"><CircleAlert aria-hidden="true" /><span>{error}</span></div>}
      <label className="remember-me-option"><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} /><span>{t("auth.rememberMe")}</span></label>
      <button className="login-submit" disabled={loading} type="submit">{loading && <LoaderCircle className="login-spinner" aria-hidden="true" />}<span>{t(loading ? "auth.signingIn" : "auth.signIn")}</span></button>
    </form>
  </main>;
}
