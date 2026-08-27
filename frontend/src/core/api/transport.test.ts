import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorFromResponse, request, resetAuthenticationState } from "./transport";

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
      hint: "Check the WebNAS backend logs.",
      upstream_status: 500,
    } }), 500, "Internal Server Error");

    expect(error).toMatchObject({ status: 500, code: "PROXMOX_INTERNAL_ERROR" });
    expect(error.message).toContain("HTTP 500");
    expect(error.message).toContain("Kod: PROXMOX_INTERNAL_ERROR");
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

  it("throws ApiError for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("failed", { status: 500, statusText: "Failure" })));
    await expect(request("/api/example")).rejects.toBeInstanceOf(ApiError);
  });
});
