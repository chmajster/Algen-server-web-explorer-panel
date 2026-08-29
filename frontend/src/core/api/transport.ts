export type HealthStatus = {
  status: "ok";
  service: string;
  deployment_phase?: "switching" | "draining" | null;
  update_id?: string | null;
};

type AuthSession = { username: string; home: string; csrf_token: string };
type BootstrapResponse = {
  user: AuthSession;
  profile: unknown;
  tasks: unknown;
  task_scope: "all" | "own" | "none";
  update_progress: unknown;
  update_detailed: boolean;
};
type AuthenticationInvalidatedListener = () => void;
type ErrorLanguage = "pl-PL" | "en-US";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public field?: string, public details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
  }
}

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const authenticationInvalidatedListeners = new Set<AuthenticationInvalidatedListener>();
const inFlightGets = new Map<string, Promise<unknown>>();
const seededGets = new Map<string, unknown>();
const CSRF_ERROR_COPY: Record<ErrorLanguage, {
  title: string;
  genericReason: string;
  missingHeader: string;
  tokenMismatch: string;
  hint: string;
  request: string;
  code: string;
}> = {
  "pl-PL": {
    title: "Sesja wymaga odświeżenia lub token bezpieczeństwa jest nieprawidłowy",
    genericReason: "Żądanie zostało odrzucone, ponieważ nie udało się potwierdzić tokenu CSRF bieżącej sesji.",
    missingHeader: "Żądanie nie zawierało wymaganego nagłówka X-CSRF-Token.",
    tokenMismatch: "Przesłany token CSRF nie odpowiada bieżącej uwierzytelnionej sesji.",
    hint: "Odśwież stronę i spróbuj ponownie. Jeśli problem nadal występuje, wyloguj się i zaloguj ponownie.",
    request: "Żądanie",
    code: "Kod błędu",
  },
  "en-US": {
    title: "The session needs to be refreshed or the security token is invalid",
    genericReason: "The request was rejected because the CSRF token for the current session could not be verified.",
    missingHeader: "The request did not include the required X-CSRF-Token header.",
    tokenMismatch: "The submitted CSRF token does not match the current authenticated session.",
    hint: "Refresh the page and try again. If the problem persists, sign out and sign in again.",
    request: "Request",
    code: "Error code",
  },
};
let csrfToken = "";
let sessionGeneration = 0;
let sessionSync: Promise<AuthSession> | null = null;
let bootstrapSync: Promise<AuthSession> | null = null;
let apiBaseUrl = "";

if (typeof localStorage !== "undefined") localStorage.removeItem("webnas_csrf");

function clearReadCaches() {
  inFlightGets.clear();
  seededGets.clear();
}

export function setApiBaseUrl(baseUrl: string) {
  apiBaseUrl = baseUrl.replace(/\/+$/, "");
  clearReadCaches();
}
export function apiAt(baseUrl: string, path: string) { return baseUrl ? `${baseUrl.replace(/\/+$/, "")}${path}` : path; }
export function healthWebSocketUrl() {
  const pageUrl = typeof window !== "undefined" ? window.location.href : "http://localhost/";
  const target = new URL(apiAt(apiBaseUrl, "/api/health/ws"), pageUrl);
  target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
  return target.toString();
}

function clearAuthenticationState(expectedGeneration?: number, notify = true) {
  if (expectedGeneration !== undefined && expectedGeneration !== sessionGeneration) return;
  sessionGeneration += 1;
  csrfToken = "";
  sessionSync = null;
  bootstrapSync = null;
  clearReadCaches();
  if (typeof localStorage !== "undefined") localStorage.removeItem("webnas_csrf");
  if (notify) authenticationInvalidatedListeners.forEach((listener) => listener());
}

export function onAuthenticationInvalidated(listener: AuthenticationInvalidatedListener) {
  authenticationInvalidatedListeners.add(listener);
  return () => { authenticationInvalidatedListeners.delete(listener); };
}

export function resetAuthenticationState() { clearAuthenticationState(undefined, false); }
function isReplayableBody(body: BodyInit | null | undefined) { return !body || typeof ReadableStream === "undefined" || !(body instanceof ReadableStream); }

function diagnosticValue(details: Record<string, unknown> | undefined, key: string): string {
  const value = details?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function currentErrorLanguage(): ErrorLanguage {
  if (typeof localStorage !== "undefined") {
    const configured = localStorage.getItem("webnas_language");
    if (configured === "en-US" || configured === "pl-PL") return configured;
  }
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("en")) return "en-US";
  return "pl-PL";
}

function knownErrorMessage(code: string | undefined, details?: Record<string, unknown>): string | null {
  if (code !== "INVALID_CSRF_TOKEN") return null;
  const copy = CSRF_ERROR_COPY[currentErrorLanguage()];
  const reasonCode = diagnosticValue(details, "reason_code");
  const endpoint = diagnosticValue(details, "endpoint");
  const method = diagnosticValue(details, "request_method");
  const reason = reasonCode === "missing_header"
    ? copy.missingHeader
    : reasonCode === "token_mismatch"
      ? copy.tokenMismatch
      : copy.genericReason;
  const request = [method, endpoint].filter(Boolean).join(" ");
  return `${copy.title}. ${reason} ${copy.hint}${request ? ` ${copy.request}: ${request}.` : ""} ${copy.code}: INVALID_CSRF_TOKEN.`;
}

function enrichErrorMessage(message: string, status: number, code?: string, details?: Record<string, unknown>): string {
  const known = knownErrorMessage(code, details);
  if (known) return known;

  const stage = diagnosticValue(details, "stage");
  const endpoint = diagnosticValue(details, "endpoint");
  const reason = diagnosticValue(details, "reason");
  const hint = diagnosticValue(details, "hint");
  const requestId = diagnosticValue(details, "request_id");
  const upstreamStatus = diagnosticValue(details, "upstream_status");
  const hasDiagnostics = Boolean(stage || endpoint || reason || hint || requestId || upstreamStatus);
  if (!hasDiagnostics && status < 500) return message;

  const parts = [`HTTP ${status}`];
  if (code) parts.push(`Kod: ${code}`);
  if (requestId) parts.push(`ID błędu: ${requestId}`);
  if (stage) parts.push(`Etap: ${stage.toUpperCase()}`);
  if (endpoint) parts.push(`Endpoint: ${endpoint}`);
  if (reason) parts.push(`Przyczyna: ${reason}`);
  if (upstreamStatus && upstreamStatus !== "0") parts.push(`HTTP upstream: ${upstreamStatus}`);
  if (hint) parts.push(`Sugestia: ${hint}`);
  if (!hasDiagnostics) parts.push("Backend nie zwrócił szczegółów diagnostycznych; sprawdź logi serwera WebNAS.");
  return `${message || "Błąd API"} — ${parts.join(" · ")}`;
}

export function errorFromResponse(body: string, status: number, statusText: string) {
  let message = body || statusText || `HTTP ${status}`;
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
  if (!code && status === 403 && message === "Invalid CSRF token") code = "INVALID_CSRF_TOKEN";
  return new ApiError(enrichErrorMessage(message, status, code, details), status, code, field, details);
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

function isBootstrapResponse(value: unknown): value is BootstrapResponse {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<BootstrapResponse>;
  const user = data.user as Partial<AuthSession> | undefined;
  return Boolean(
    user
    && typeof user.username === "string"
    && typeof user.home === "string"
    && typeof user.csrf_token === "string"
    && (data.task_scope === "all" || data.task_scope === "own" || data.task_scope === "none")
    && typeof data.update_detailed === "boolean",
  );
}

function seedBootstrap(data: BootstrapResponse) {
  seededGets.set("/api/settings/me", data.profile);
  if (data.task_scope === "all") seededGets.set("/api/admin/transfers", data.tasks);
  else if (data.task_scope === "own") seededGets.set("/api/files/tasks", data.tasks);
  seededGets.set(
    data.update_detailed ? "/api/admin/system/updates/progress" : "/api/system/update-status",
    data.update_progress,
  );
}

function synchronizeSession(force = false): Promise<AuthSession> {
  if (sessionSync) return sessionSync;
  if (force) { sessionGeneration += 1; csrfToken = ""; clearReadCaches(); }
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

function bootstrapSession(): Promise<AuthSession> {
  if (bootstrapSync) return bootstrapSync;
  const generation = sessionGeneration;
  const pending = send<unknown>("/api/bootstrap", { method: "GET", cache: "no-store" })
    .then((value) => {
      if (generation !== sessionGeneration) throw new ApiError("Session bootstrap was superseded", 409);
      if (!isBootstrapResponse(value)) return synchronizeSession();
      csrfToken = value.user.csrf_token;
      seedBootstrap(value);
      return value.user;
    })
    .catch((error: unknown) => {
      if (generation !== sessionGeneration) {
        if (error instanceof ApiError && error.status === 409) throw error;
        throw new ApiError("Session bootstrap was superseded", 409);
      }
      if (error instanceof ApiError && error.status === 401) {
        clearAuthenticationState(generation);
        throw error;
      }
      return synchronizeSession();
    })
    .finally(() => { if (bootstrapSync === pending) bootstrapSync = null; });
  bootstrapSync = pending;
  return pending;
}

function isInvalidCsrfError(error: unknown): error is ApiError {
  return error instanceof ApiError
    && error.status === 403
    && (error.code === "INVALID_CSRF_TOKEN" || error.message === "Invalid CSRF token");
}

async function executeRequest<T>(url: string, options: RequestInit, method: string): Promise<T> {
  const requiresCsrf = MUTATING_METHODS.has(method) && url !== "/api/auth/login";
  if (requiresCsrf && !csrfToken) await synchronizeSession();
  const generation = sessionGeneration;
  try {
    return await send<T>(url, options, requiresCsrf ? csrfToken : "");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) { clearAuthenticationState(generation); throw error; }
    if (!requiresCsrf || !isInvalidCsrfError(error) || !isReplayableBody(options.body)) throw error;
    await synchronizeSession(true);
    return send<T>(url, options, csrfToken);
  }
}

function getDedupeKey(url: string, options: RequestInit, method: string) {
  if (method !== "GET" || options.body !== undefined || options.signal || options.headers) return null;
  return `${sessionGeneration}:${apiBaseUrl}:${url}`;
}

export function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const key = getDedupeKey(url, options, method);
  if (key && seededGets.has(url)) {
    const seeded = seededGets.get(url) as T;
    seededGets.delete(url);
    return Promise.resolve(seeded);
  }
  if (!key) return executeRequest<T>(url, options, method);
  const existing = inFlightGets.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const pending = executeRequest<T>(url, options, method).finally(() => {
    if (inFlightGets.get(key) === pending) inFlightGets.delete(key);
  });
  inFlightGets.set(key, pending);
  return pending;
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
  try {
    return await bootstrapSession();
  } catch (error) {
    if (generation !== sessionGeneration) throw new ApiError("Login was superseded", 409);
    if (error instanceof ApiError && error.status === 401) throw error;
    return data;
  }
}

export function me() { return bootstrapSession(); }
export function logout() { return request("/api/auth/logout", { method: "POST", body: "{}" }).finally(() => clearAuthenticationState()); }
