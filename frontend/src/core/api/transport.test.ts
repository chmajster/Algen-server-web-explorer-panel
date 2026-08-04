import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorFromResponse, request, resetAuthenticationState } from "./transport";

afterEach(() => { vi.unstubAllGlobals(); resetAuthenticationState(); });

describe("shared API transport", () => {
  it("decodes the common structured error contract", () => {
    const error = errorFromResponse(JSON.stringify({ error: { code: "DENIED", message: "Denied", field: "path", details: { policy: "files" } } }), 403, "Forbidden");
    expect(error).toMatchObject({ status: 403, code: "DENIED", message: "Denied", field: "path" });
    expect(error.details).toEqual({ policy: "files" });
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
