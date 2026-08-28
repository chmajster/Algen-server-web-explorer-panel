import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, errorFromResponse, request, resetAuthenticationState } from "./transport";

const ok = (data: unknown) => ({
  ok: true,
  status: 200,
  statusText: "OK",
  json: async () => data,
});

const csrfFailure = (reasonCode: "missing_header" | "token_mismatch" = "token_mismatch") => ({
  ok: false,
  status: 403,
  statusText: "Forbidden",
  text: async () => JSON.stringify({
    detail: {
      code: "INVALID_CSRF_TOKEN",
      message: "Invalid CSRF token",
      reason_code: reasonCode,
      reason: reasonCode === "missing_header"
        ? "The X-CSRF-Token header is missing."
        : "The submitted CSRF token does not match the current authenticated session.",
      hint: "Refresh the page and retry the operation. If the problem persists, sign out and sign in again.",
      recovery: "refresh_or_reauthenticate",
      endpoint: "/api/settings",
      request_method: "PATCH",
      expected_header: "X-CSRF-Token",
      csrf_header_present: reasonCode !== "missing_header",
      session_valid: true,
    },
  }),
});

const session = (csrfToken: string) => ok({ username: "alice", home: "/home/alice", csrf_token: csrfToken });

describe("CSRF API error presentation", () => {
  beforeEach(() => {
    resetAuthenticationState();
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("returns an expanded Polish message and preserves diagnostics", () => {
    localStorage.setItem("webnas_language", "pl-PL");
    const error = errorFromResponse(JSON.stringify({
      detail: {
        code: "INVALID_CSRF_TOKEN",
        message: "Invalid CSRF token",
        reason_code: "token_mismatch",
        endpoint: "/api/settings",
        request_method: "PATCH",
        session_valid: true,
      },
    }), 403, "Forbidden");

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, code: "INVALID_CSRF_TOKEN" });
    expect(error.message).toContain("Sesja wymaga odświeżenia lub token bezpieczeństwa jest nieprawidłowy");
    expect(error.message).toContain("Przesłany token CSRF nie odpowiada bieżącej uwierzytelnionej sesji");
    expect(error.message).toContain("Odśwież stronę i spróbuj ponownie");
    expect(error.message).toContain("Żądanie: PATCH /api/settings");
    expect(error.message).toContain("Kod błędu: INVALID_CSRF_TOKEN");
    expect(error.details).toMatchObject({ reason_code: "token_mismatch", session_valid: true });
  });

  it("returns the translated English message when English is selected", () => {
    localStorage.setItem("webnas_language", "en-US");
    const response = csrfFailure("missing_header");

    return response.text().then((body) => {
      const error = errorFromResponse(body, 403, "Forbidden");
      expect(error.message).toContain("The session needs to be refreshed or the security token is invalid");
      expect(error.message).toContain("The request did not include the required X-CSRF-Token header");
      expect(error.message).toContain("Refresh the page and try again");
      expect(error.message).toContain("Request: PATCH /api/settings");
      expect(error.message).toContain("Error code: INVALID_CSRF_TOKEN");
    });
  });

  it("translates the legacy string response and assigns the stable error code", () => {
    localStorage.setItem("webnas_language", "pl-PL");
    const error = errorFromResponse(JSON.stringify({ detail: "Invalid CSRF token" }), 403, "Forbidden");

    expect(error.code).toBe("INVALID_CSRF_TOKEN");
    expect(error.message).toContain("Sesja wymaga odświeżenia");
    expect(error.message).toContain("nie udało się potwierdzić tokenu CSRF");
  });

  it("recognizes the structured code, refreshes the session and retries once", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(session("stale-token"))
      .mockResolvedValueOnce(csrfFailure("token_mismatch"))
      .mockResolvedValueOnce(session("fresh-token"))
      .mockResolvedValueOnce(ok({ saved: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/api/settings", { method: "PATCH", body: "{}" })).resolves.toEqual({ saved: true });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/auth/me",
      "/api/settings",
      "/api/auth/me",
      "/api/settings",
    ]);
    const retryHeaders = (fetchMock.mock.calls[3][1] as RequestInit).headers as Headers;
    expect(retryHeaders.get("x-csrf-token")).toBe("fresh-token");
  });

  it("returns the expanded localized message after the one automatic retry also fails", async () => {
    localStorage.setItem("webnas_language", "pl-PL");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(session("stale-token"))
      .mockResolvedValueOnce(csrfFailure("token_mismatch"))
      .mockResolvedValueOnce(session("fresh-token"))
      .mockResolvedValueOnce(csrfFailure("token_mismatch"));
    vi.stubGlobal("fetch", fetchMock);

    const error = await request("/api/settings", { method: "PATCH", body: "{}" }).catch((reason) => reason as ApiError);

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(error).toMatchObject({ status: 403, code: "INVALID_CSRF_TOKEN" });
    expect(error.message).toContain("Odśwież stronę i spróbuj ponownie");
    expect(error.message).toContain("Kod błędu: INVALID_CSRF_TOKEN");
  });
});
