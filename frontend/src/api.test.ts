import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, login } from "./api";

describe("API errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("extracts a structured error instead of displaying the JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      text: async () => JSON.stringify({ detail: { code: "already_exists", field: "name", message: "Already exists" } })
    }));

    const error = await api.mkdir("/home/alice/existing").catch((reason) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Already exists", status: 409, code: "already_exists", field: "name" });
  });

  it("formats FastAPI validation errors with their field names", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
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
      status: 422,
      field: "apmid_id",
      message: "apmid_id: Field required; app_id: Extra inputs are not permitted",
    });
  });

  it("serializes the canonical permanent enrollment-token HTTP body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "token" }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.createHostsManagerEnrollmentToken({
      agent_port: 8443,
      apmid_id: "apmid-app",
      apply_hostname: true,
      bootstrap_os: "linux",
      bound_address: "",
      environment_id: "production",
      expires_minutes: null,
      group_ids: [],
      hostname_pattern_id: null,
      location: "",
      mode: "permanent",
      onboard_ansible: false,
      report_interval_seconds: 300,
      require_approval: true,
      tags: [],
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toEqual({
      agent_port: 8443, apmid_id: "apmid-app", apply_hostname: true, bootstrap_os: "linux",
      bound_address: "", environment_id: "production", expires_minutes: null, group_ids: [],
      hostname_pattern_id: null, location: "", mode: "permanent", onboard_ansible: false,
      report_interval_seconds: 300, require_approval: true, tags: [],
    });
    expect(body).not.toHaveProperty("app_id");
    expect(typeof body.agent_port).toBe("number");
    expect(typeof body.apply_hostname).toBe("boolean");
    expect(Array.isArray(body.group_ids)).toBe(true);
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
      cache: "no-store",
      credentials: "include",
      signal: controller.signal,
    }));
  });

  it("requests a package operation plan with POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ module_id: "samba", action: "uninstall" })
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.appPlan("samba", "uninstall", true);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/apps/samba/plan?action=uninstall&remove_data=true",
      expect.objectContaining({ method: "POST", body: "{}", credentials: "include" })
    );
  });

  it("loads the minimal network roots endpoint for File Explorer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await api.mountRoots();

    expect(fetchMock).toHaveBeenCalledWith("/api/mounts/roots", expect.objectContaining({ credentials: "include" }));
  });

  it("loads local disks for File Explorer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await api.localDisks();

    expect(fetchMock).toHaveBeenCalledWith("/api/files/local-disks", expect.objectContaining({ credentials: "include" }));
  });

  it("queues a package reinstall through its dedicated endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ job: { id: "job-1" } }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.appAction("samba", "reinstall");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/apps/samba/reinstall",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ confirm_plan: true, remove_data: false }), credentials: "include" })
    );
  });

  it("loads authenticated host information for Settings", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ hostname: "nas-one" }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.hostInfo();

    expect(fetchMock).toHaveBeenCalledWith("/api/system/host-info", expect.objectContaining({ credentials: "include" }));
  });

  it("sends the remember-me choice only in the login request body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ username: "alice", home: "/home/alice", csrf_token: "csrf" })
    });
    vi.stubGlobal("fetch", fetchMock);

    await login("alice", "secret", true);

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ username: "alice", password: "secret", remember_me: true }),
      credentials: "include",
    }));
    expect(localStorage.getItem("webnas_csrf")).toBe("csrf");
  });

  it("loads and saves a text file through the editor API", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ content: "hello", mtime_ns: "100" }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ ok: true, mtime_ns: "200" }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.readText("/home/alice/notes.txt");
    await api.writeText("/home/alice/notes.txt", "updated", "100");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/files/text?path=%2Fhome%2Falice%2Fnotes.txt", expect.objectContaining({ credentials: "include" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/files/text", expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ path: "/home/alice/notes.txt", content: "updated", expected_mtime_ns: "100" }),
      credentials: "include",
    }));
  });
});
