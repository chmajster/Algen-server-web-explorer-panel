import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, health, rawRequest, resetAuthenticationState, setApiBaseUrl } from "./transport";

afterEach(() => {
  vi.unstubAllGlobals();
  setApiBaseUrl("");
  resetAuthenticationState();
});

describe("raw API transport", () => {
  it("synchronizes the session and sends CSRF for mutating raw responses", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/auth/me") {
        return Promise.resolve(new Response(JSON.stringify({ username: "alice", home: "/home/alice", csrf_token: "csrf-token" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }));
      }
      if (url === "/api/logs/export") {
        expect(new Headers(init?.headers).get("x-csrf-token")).toBe("csrf-token");
        expect(init?.credentials).toBe("include");
        return Promise.resolve(new Response("exported", { status: 200 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await rawRequest("/api/logs/export", { method: "POST", body: "{}" });

    await expect(response.text()).resolves.toBe("exported");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/auth/me", "/api/logs/export"]);
  });

  it("uses the configured API base URL for raw requests", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "https://new-host.example/api/auth/me") {
        return Promise.resolve(new Response(JSON.stringify({ username: "alice", home: "/home/alice", csrf_token: "csrf-token" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }));
      }
      if (url === "https://new-host.example/api/logs/export") return Promise.resolve(new Response("ok", { status: 200 }));
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    setApiBaseUrl("https://new-host.example/");

    await rawRequest("/api/logs/export", { method: "POST", body: "{}" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "https://new-host.example/api/auth/me",
      "https://new-host.example/api/logs/export",
    ]);
  });

  it("rejects client errors from the health endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Not Found", { status: 404, statusText: "Not Found" })));

    await expect(health()).rejects.toBeInstanceOf(ApiError);
  });
});
