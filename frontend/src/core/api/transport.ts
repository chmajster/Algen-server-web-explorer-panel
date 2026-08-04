export type HealthStatus = {
  status: "ok";
  service: string;
  deployment_phase?: "switching" | "draining" | null;
  update_id?: string | null;
};

type AuthSession = { username: string; home: string; csrf_token: string };
type AuthenticationInvalidatedListener = () => void;

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public field?: string, public details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
  }
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const authenticationInvalidatedListeners = new Set<AuthenticationInvalidatedListener>();
let csrfToken = "";
let sessionGeneration = 0;
let sessionSync: Promise<AuthSession> | null = null;
let apiBaseUrl = "";

if (typeof localStorage !== "undefined") localStorage.removeItem("webnas_csrf");

export function setApiBaseUrl(baseUrl: string) { apiBaseUrl = baseUrl.replace(/\/+$/, ""); }
export function apiAt(baseUrl: string, path: string) { return baseUrl ? `${baseUrl.replace(/\/+$/, "")}${path}` : path; }

function clearAuthenticationState(expectedGeneration?: number, notify = true) {
  if (expectedGeneration !== undefined && expectedGeneration !== sessionGeneration) return;
  sessionGeneration += 1;
  csrfToken = "";
  sessionSync = null;
  if (typeof localStorage !== "undefined") localStorage.removeItem("webnas_csrf");
  if (notify) authenticationInvalidatedListeners.forEach((listener) => listener());
}

export function onAuthenticationInvalidated(listener: AuthenticationInvalidatedListener) {
  authenticationInvalidatedListeners.add(listener);
  return () => { authenticationInvalidatedListeners.delete(listener); };
}

export function resetAuthenticationState() { clearAuthenticationState(undefined, false); }
function isReplayableBody(body: BodyInit | null | undefined) { return !body || typeof ReadableStream === "undefined" || !(body instanceof ReadableStream); }

export function errorFromResponse(body: string, status: number, statusText: string) {
  let message = body || statusText;
  let code: string | undefined;
  let field: string | undefined;
  let details: Record<string, unknown> | undefined;
  try {
    const payload = JSON.parse(body) as {
      error?: { code?: string; message?: string; field?: string; details?: Record<string, unknown> } | null;
      detail?: string | ({ code?: string; message?: string; field?: string } & Record<string, unknown>) | Array<{ loc?: Array<string | number>; msg?: string }>;
    };
    if (payload.error) {
      message = payload.error.message || message;
      code = payload.error.code;
      field = payload.error.field;
      details = payload.error.details;
    }
    else if (typeof payload.detail === "string") message = payload.detail;
    else if (Array.isArray(payload.detail)) {
      const errors = payload.detail.map((error) => `${(error.loc || []).filter((part) => part !== "body").join(".") || "request"}: ${error.msg || "Invalid value"}`);
      if (errors.length) message = errors.join("; ");
      field = payload.detail[0]?.loc?.filter((part) => part !== "body").join(".") || undefined;
      details = { errors: payload.detail };
    } else if (payload.detail) {
      message = payload.detail.message || message;
      code = payload.detail.code;
      field = payload.detail.field;
      details = payload.detail;
    }
  } catch { /* Non-JSON responses retain their original text. */ }
  return new ApiError(message, status, code, field, details);
}

async function send<T>(url: string, options: RequestInit, token = ""): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body instanceof Blob) headers.set("Content-Type", "application/octet-stream");
  else if (options.body !== undefined && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("x-csrf-token", token);
  const target = apiBaseUrl && url.startsWith("/") ? `${apiBaseUrl}${url}` : url;
  const response = await fetch(target, { ...options, headers, credentials: "include" });
  if (!response.ok) throw errorFromResponse(await response.text(), response.status, response.statusText);
  return response.json() as Promise<T>;
}

function synchronizeSession(force = false): Promise<AuthSession> {
  if (sessionSync) return sessionSync;
  if (force) { sessionGeneration += 1; csrfToken = ""; }
  const generation = sessionGeneration;
  const pending = send<AuthSession>("/api/auth/me", { method: "GET", cache: "no-store" })
    .then((data) => {
      if (generation !== sessionGeneration) throw new ApiError("Session synchronization was superseded", 409);
      csrfToken = data.csrf_token;
      return data;
    })
    .catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 401) clearAuthenticationState(generation);
      throw error;
    })
    .finally(() => { if (sessionSync === pending) sessionSync = null; });
  sessionSync = pending;
  return pending;
}

export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const requiresCsrf = MUTATING_METHODS.has(method) && url !== "/api/auth/login";
  if (requiresCsrf && !csrfToken) await synchronizeSession();
  const generation = sessionGeneration;
  try {
    return await send<T>(url, options, requiresCsrf ? csrfToken : "");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { clearAuthenticationState(generation); throw error; }
    const invalidCsrf = error instanceof ApiError && error.status === 403 && error.message === "Invalid CSRF token";
    if (!requiresCsrf || !invalidCsrf || !isReplayableBody(options.body)) throw error;
    await synchronizeSession(true);
    return send<T>(url, options, csrfToken);
  }
}

export async function health(signal?: AbortSignal): Promise<HealthStatus> {
  const target = apiBaseUrl ? `${apiBaseUrl}/api/health` : "/api/health";
  const response = await fetch(target, { cache: "no-store", credentials: "include", headers: { Accept: "application/json" }, signal });
  if (response.status >= 500) throw new ApiError(response.statusText || "Backend health check failed", response.status);
  if (!response.ok) return { status: "ok", service: "webnas" };
  return response.json() as Promise<HealthStatus>;
}

export async function enrollmentScript(url: string, token: string): Promise<Blob> {
  const target = apiBaseUrl && url.startsWith("/") ? `${apiBaseUrl}${url}` : url;
  const response = await fetch(target, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!response.ok) throw new ApiError("Enrollment script is unavailable", response.status);
  return response.blob();
}

export async function login(username: string, password: string, rememberMe = false) {
  clearAuthenticationState(undefined, false);
  const generation = sessionGeneration;
  const data = await send<AuthSession>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password, remember_me: rememberMe }) });
  if (generation !== sessionGeneration) throw new ApiError("Login was superseded", 409);
  csrfToken = data.csrf_token;
  return data;
}

export function me() { return synchronizeSession(); }
export function logout() { return request("/api/auth/logout", { method: "POST", body: "{}" }).finally(() => clearAuthenticationState()); }
