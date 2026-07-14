import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

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
});
