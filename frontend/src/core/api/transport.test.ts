import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorFromResponse, me, request, resetAuthenticationState } from "./transport";

afterEach(() => { vi.unstubAllGlobals(); resetAuthenticationState(); });

describe("shared API transport", () => {
  it("decodes the common structured error contract", () => {
    const error = errorFromResponse(JSON.stringify({ error: { code: "DENIED", message: "Denied", field: "path", details: { policy: "files" } } }), 403, "Forbidden");
    expect(error).toMatchObject({ status: 403, code: "DENIED", message: "Denied", field: "path" });
    expect(error.details).toEqual({ policy: "files" });
  });

  it("surfaces FastAPI diagnostic details in the visible error message", () => {
    const error = errorFromResponse(JSON.stringify({ detail: {
      code: "PROXMOX_INTERNAL_ERROR",
      message: "Proxmox Manager encountered an unexpected server error.",
      stage: "configuration",
      endpoint: "https://10.0.0.10:8006",
      reason: "PermissionError",
      request_id: "abc123def456",
      hint: "Check the WebNAS backend logs.",
      upstream_status: 500,
    } }), 500, "Internal Server Error");

    expect(error).toMatchObject({ status: 500, code: "PROXMOX_INTERNAL_ERROR" });
    expect(error.message).toContain("HTTP 500");
    expect(error.message).toContain("Kod: PROXMOX_INTERNAL_ERROR");
    expect(error.message).toContain("ID błędu: abc123def456");
    expect(error.message).toContain("Etap: CONFIGURATION");
    expect(error.message).toContain("Endpoint: https://10.0.0.10:8006");
    expect(error.message).toContain("Przyczyna: PermissionError");
    expect(error.message).toContain("Sugestia: Check the WebNAS backend logs.");
  });

  it("explains an unstructured backend 500 instead of showing only Internal Server Error", () => {
    const error = errorFromResponse("Internal Server Error", 500, "Internal Server Error");
    expect(error.message).toContain("Internal Server Error");
    expect(error.message).toContain("HTTP 500");
    expect(error.message).toContain("Backend nie zwrócił szczegółów diagnostycznych");
  });

  it("adds cookies and decodes typed JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request<{ ok: boolean }>("/api/example")).resolves.toEqual({ ok: true });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include" });
  });

  it("deduplicates concurrent GET requests for the same resource", async () => {
    let resolveResponse: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { resolveResponse = resolve; }));
    vi.stubGlobal("fetch", fetchMock);

    const first = request<{ ok: boolean }>("/api/shared");
    const second = request<{ ok: boolean }>("/api/shared");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveResponse?.(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
    await expect(Promise.all([first, second])).resolves.toEqual([{ ok: true }, { ok: true }]);
  });

  it("serves startup settings, tasks and update state from one bootstrap request", async () => {
    const profile = { username: "test", permissions: ["transfers.view_own"], language: "pl-PL" };
    const tasks = [{ id: "task-1" }];
    const updateProgress = { state: "idle", running: false };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      user: { username: "test", home: "/home/test", csrf_token: "csrf" },
      profile,
      tasks,
      task_scope: "own",
      update_progress: updateProgress,
      update_detailed: false,
      update_completion: null,
    }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(me()).resolves.toEqual({ username: "test", home: "/home/test", csrf_token: "csrf" });
    await expect(request("/api/settings/me")).resolves.toEqual(profile);
    await expect(request("/api/files/tasks")).resolves.toEqual(tasks);
    await expect(request("/api/system/update-status")).resolves.toEqual(updateProgress);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/bootstrap");
  });

  it("keeps update completion off the bootstrap critical path", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/bootstrap") return Promise.resolve(new Response(JSON.stringify({
        user: { username: "test", home: "/home/test", csrf_token: "csrf" },
        profile: { username: "test", permissions: ["updates.view"] },
        tasks: [],
        task_scope: "none",
        update_progress: { state: "idle" },
        update_detailed: true,
      }), { status: 200, headers: { "content-type": "application/json" } }));
      if (url === "/api/admin/system/updates/completion") return Promise.resolve(new Response(JSON.stringify({ notice: null }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await me();
    await expect(request("/api/admin/system/updates/completion")).resolves.toEqual({ notice: null });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/bootstrap", "/api/admin/system/updates/completion"]);
  });

  it("does not fall back after a bootstrap request is superseded", async () => {
    let resolveBootstrap: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/bootstrap") return new Promise<Response>((resolve) => { resolveBootstrap = resolve; });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const pending = me();
    resetAuthenticationState();
    resolveBootstrap?.(new Response(JSON.stringify({
      user: { username: "old", home: "/home/old", csrf_token: "old-csrf" },
      profile: { username: "old", permissions: [] },
      tasks: [],
      task_scope: "none",
      update_progress: { state: "idle" },
      update_detailed: false,
    }), { status: 200, headers: { "content-type": "application/json" } }));

    await expect(pending).rejects.toMatchObject({ status: 409 });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/bootstrap"]);
  });

  it("falls back to the legacy session endpoint when bootstrap is unavailable", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/bootstrap") return Promise.resolve(new Response("missing", { status: 404, statusText: "Not Found" }));
      if (url === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ username: "test", home: "/home/test", csrf_token: "csrf" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(me()).resolves.toEqual({ username: "test", home: "/home/test", csrf_token: "csrf" });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/bootstrap", "/api/auth/me"]);
  });

  it("does not deduplicate mutating requests", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ ok: true, csrf_token: "csrf" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));
    vi.stubGlobal("fetch", fetchMock);
    await Promise.all([
      request("/api/example", { method: "POST", body: "{}" }),
      request("/api/example", { method: "POST", body: "{}" }),
    ]);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/example")).toHaveLength(2);
  });

  it("throws ApiError for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("failed", { status: 500, statusText: "Failure" })));
    await expect(request("/api/example")).rejects.toBeInstanceOf(ApiError);
  });
});