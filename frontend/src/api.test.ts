import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, login, logout, me, onAuthenticationInvalidated, resetAuthenticationState } from "./api";

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const failure = (status: number, detail: string) => ({
  ok: false,
  status,
  statusText: status === 401 ? "Unauthorized" : "Forbidden",
  text: async () => JSON.stringify({ detail }),
});
const userSession = (csrfToken = "csrf") => ({ username: "alice", home: "/home/alice", csrf_token: csrfToken });
const session = (csrfToken = "csrf") => ok(userSession(csrfToken));
const bootstrap = (csrfToken = "csrf") => ok({
  user: userSession(csrfToken),
  profile: { username: "alice", home: "/home/alice", permissions: [] },
  tasks: [],
  task_scope: "none",
  update_progress: { state: "idle" },
  update_detailed: false,
});

describe("API errors and session synchronization", () => {
  beforeEach(() => resetAuthenticationState());
  afterEach(() => vi.unstubAllGlobals());

  it("extracts a structured error instead of displaying the JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce({
      ok: false, status: 409, statusText: "Conflict",
      text: async () => JSON.stringify({ detail: { code: "already_exists", field: "name", message: "Already exists" } }),
    }));

    const error = await api.mkdir("/home/alice/existing").catch((reason) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Already exists", status: 409, code: "already_exists", field: "name" });
  });

  it("formats FastAPI validation errors with their field names", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce({
      ok: false, status: 422, statusText: "Unprocessable Entity",
      text: async () => JSON.stringify({ detail: [
        { loc: ["body", "apmid_id"], msg: "Field required", type: "missing" },
        { loc: ["body", "app_id"], msg: "Extra inputs are not permitted", type: "extra_forbidden" },
      ] }),
    }));

    const error = await api.createHostsManagerEnrollmentToken({
      bootstrap_os: "linux", apply_hostname: true, expires_minutes: null, mode: "permanent",
      apmid_id: "apmid-app", environment_id: "production", hostname_pattern_id: null,
      location: "", tags: [], group_ids: [], require_approval: true, onboard_ansible: false,
    }).catch((reason) => reason);

    expect(error).toMatchObject({
      status: 422, field: "apmid_id",
      message: "apmid_id: Field required; app_id: Extra inputs are not permitted",
    });
  });

  it("serializes the canonical permanent enrollment-token HTTP body", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(ok({ id: "token" }));
    vi.stubGlobal("fetch", fetchMock);

    await api.createHostsManagerEnrollmentToken({
      agent_port: 8443, apmid_id: "apmid-app", apply_hostname: true, bootstrap_os: "linux",
      bound_address: "", environment_id: "production", expires_minutes: null, group_ids: [],
      hostname_pattern_id: null, location: "", mode: "permanent", onboard_ansible: false,
      report_interval_seconds: 300, require_approval: true, tags: [],
    });

    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toEqual({
      agent_port: 8443, apmid_id: "apmid-app", apply_hostname: true, bootstrap_os: "linux",
      bound_address: "", environment_id: "production", expires_minutes: null, group_ids: [],
      hostname_pattern_id: null, location: "", mode: "permanent", onboard_ansible: false,
      report_interval_seconds: 300, require_approval: true, tags: [],
    });
    expect(body).not.toHaveProperty("app_id");
  });

  it("uses the public no-cache health check and treats only server errors as unavailable", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 401, statusText: "Unauthorized" })
      .mockResolvedValueOnce({ ok: false, status: 503, statusText: "Service Unavailable" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.health(controller.signal)).resolves.toEqual({ status: "ok", service: "webnas" });
    await expect(api.health(controller.signal)).rejects.toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/health", expect.objectContaining({
      cache: "no-store", credentials: "include", signal: controller.signal,
    }));
  });

  it("returns the planned deployment phase reported by health", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({
      status: "ok", service: "webnas", deployment_phase: "switching", update_id: "update-1",
    })));
    await expect(api.health()).resolves.toEqual({
      status: "ok", service: "webnas", deployment_phase: "switching", update_id: "update-1",
    });
  });

  it("requests a package operation plan with POST", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(ok({ module_id: "samba", action: "uninstall" }));
    vi.stubGlobal("fetch", fetchMock);
    await api.appPlan("samba", "uninstall", true);
    expect(fetchMock).toHaveBeenNthCalledWith(2,
      "/api/apps/samba/plan?action=uninstall&remove_data=true",
      expect.objectContaining({ method: "POST", body: "{}", credentials: "include" }),
    );
  });

  it("loads public authenticated resources with credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]));
    vi.stubGlobal("fetch", fetchMock);
    await api.mountRoots();
    await api.localDisks();
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/mounts/roots", expect.objectContaining({ credentials: "include" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/files/local-disks", expect.objectContaining({ credentials: "include" }));
  });

  it("queues a package reinstall through its dedicated endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(ok({ job: { id: "job-1" } }));
    vi.stubGlobal("fetch", fetchMock);
    await api.appAction("samba", "reinstall");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/apps/samba/reinstall", expect.objectContaining({
      method: "POST", body: JSON.stringify({ confirm_plan: true, remove_data: false }), credentials: "include",
    }));
  });

  it("loads authenticated host information for Settings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ hostname: "nas-one" }));
    vi.stubGlobal("fetch", fetchMock);
    await api.hostInfo();
    expect(fetchMock).toHaveBeenCalledWith("/api/system/host-info", expect.objectContaining({ credentials: "include" }));
  });

  it("sends remember-me only in login and never persists the CSRF token", async () => {
    localStorage.setItem("webnas_csrf", "expired");
    const fetchMock = vi.fn().mockResolvedValueOnce(session()).mockResolvedValueOnce(bootstrap());
    vi.stubGlobal("fetch", fetchMock);
    await login("alice", "secret", true);
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({
      method: "POST", body: JSON.stringify({ username: "alice", password: "secret", remember_me: true }), credentials: "include",
    }));
    expect(localStorage.getItem("webnas_csrf")).toBeNull();
  });

  it("loads and saves a text file through the editor API", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok({ content: "hello", mtime_ns: "100" }))
      .mockResolvedValueOnce(session())
      .mockResolvedValueOnce(ok({ ok: true, mtime_ns: "200" }));
    vi.stubGlobal("fetch", fetchMock);
    await api.readText("/home/alice/notes.txt");
    await api.writeText("/home/alice/notes.txt", "updated", "100");
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/files/text?path=%2Fhome%2Falice%2Fnotes.txt", expect.objectContaining({ credentials: "include" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/files/text", expect.objectContaining({
      method: "PUT", body: JSON.stringify({ path: "/home/alice/notes.txt", content: "updated", expected_mtime_ns: "100" }), credentials: "include",
    }));
  });

  it("restores the current token from the session before the first mutation", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(session("current")).mockResolvedValueOnce(ok({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api.mkdir("/home/alice/new");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/auth/me", "/api/files/mkdir"]);
    const headers = (fetchMock.mock.calls[1][1] as RequestInit).headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("current");
  });

  it("refreshes a stale token and retries an invalid-CSRF mutation exactly once", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(bootstrap("stale"))
      .mockResolvedValueOnce(failure(403, "Invalid CSRF token"))
      .mockResolvedValueOnce(session("fresh"))
      .mockResolvedValueOnce(ok({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await me();
    await expect(api.mkdir("/home/alice/new")).resolves.toEqual({ ok: true });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/bootstrap", "/api/files/mkdir", "/api/auth/me", "/api/files/mkdir",
    ]);
    const headers = (fetchMock.mock.calls[3][1] as RequestInit).headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("fresh");
  });

  it("does not retry an unrelated forbidden response", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(bootstrap()).mockResolvedValueOnce(failure(403, "Permission denied"));
    vi.stubGlobal("fetch", fetchMock);
    await me();
    await expect(api.mkdir("/root/blocked")).rejects.toMatchObject({ status: 403, message: "Permission denied" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never retries an invalid-CSRF response more than once", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(bootstrap("stale"))
      .mockResolvedValueOnce(failure(403, "Invalid CSRF token"))
      .mockResolvedValueOnce(session("fresh"))
      .mockResolvedValueOnce(failure(403, "Invalid CSRF token"));
    vi.stubGlobal("fetch", fetchMock);
    await me();
    await expect(api.mkdir("/home/alice/new")).rejects.toMatchObject({ status: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("shares one session synchronization across parallel mutations", async () => {
    let resolveSession!: (value: ReturnType<typeof session>) => void;
    const pendingSession = new Promise<ReturnType<typeof session>>((resolve) => { resolveSession = resolve; });
    const fetchMock = vi.fn((url: string) => url === "/api/auth/me" ? pendingSession : Promise.resolve(ok({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const first = api.mkdir("/home/alice/one");
    const second = api.mkdir("/home/alice/two");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveSession(session("shared"));
    await Promise.all([first, second]);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth/me")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("shares one session check across concurrent callers such as React StrictMode", async () => {
    let resolveBootstrap!: (value: ReturnType<typeof bootstrap>) => void;
    const pendingBootstrap = new Promise<ReturnType<typeof bootstrap>>((resolve) => { resolveBootstrap = resolve; });
    const fetchMock = vi.fn().mockReturnValue(pendingBootstrap);
    vi.stubGlobal("fetch", fetchMock);

    const first = me();
    const second = me();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveBootstrap(bootstrap("shared"));

    await expect(Promise.all([first, second])).resolves.toEqual([userSession("shared"), userSession("shared")]);
  });

  it("prevents an older session response from replacing a newer login token", async () => {
    let resolveOldBootstrap!: (value: ReturnType<typeof bootstrap>) => void;
    const oldBootstrap = new Promise<ReturnType<typeof bootstrap>>((resolve) => { resolveOldBootstrap = resolve; });
    let bootstrapCalls = 0;
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url === "/api/bootstrap") {
        bootstrapCalls += 1;
        return bootstrapCalls === 1 ? oldBootstrap : Promise.resolve(bootstrap("login-token"));
      }
      if (url === "/api/auth/login") return Promise.resolve(session("login-token"));
      if (url === "/api/files/mkdir") return Promise.resolve(ok({ ok: true }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const oldMe = me();
    const oldMeResult = expect(oldMe).rejects.toMatchObject({ status: 409 });
    await login("alice", "secret");
    resolveOldBootstrap(bootstrap("old-token"));
    await oldMeResult;
    await api.mkdir("/home/alice/new");
    const mkdirCall = fetchMock.mock.calls.find(([url]) => url === "/api/files/mkdir");
    const headers = (mkdirCall?.[1] as RequestInit).headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("login-token");
  });

  it("clears authentication state on HTTP 401", async () => {
    const invalidated = vi.fn();
    const unsubscribe = onAuthenticationInvalidated(invalidated);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(bootstrap("active"))
      .mockResolvedValueOnce(failure(401, "Invalid or expired session"))
      .mockResolvedValueOnce(session("renewed"))
      .mockResolvedValueOnce(ok({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await me();
    await expect(api.hostInfo()).rejects.toMatchObject({ status: 401 });
    await api.mkdir("/home/alice/new");
    expect(invalidated).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[2][0]).toBe("/api/auth/me");
    unsubscribe();
  });

  it("logs out with the current token and clears it afterwards", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(bootstrap("logout-token"))
      .mockResolvedValueOnce(ok({ ok: true }))
      .mockResolvedValueOnce(failure(401, "Authentication required"));
    vi.stubGlobal("fetch", fetchMock);
    await me();
    await logout();
    const headers = (fetchMock.mock.calls[1][1] as RequestInit).headers as Headers;
    expect(headers.get("x-csrf-token")).toBe("logout-token");
    await expect(api.mkdir("/home/alice/new")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/auth/me");
  });
});
