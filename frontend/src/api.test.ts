import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

describe("API errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("extracts a structured error instead of displaying the JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      text: async () => JSON.stringify({ detail: { code: "already_exists", message: "Already exists" } })
    }));

    const error = await api.mkdir("/home/alice/existing").catch((reason) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Already exists", status: 409, code: "already_exists" });
  });
});
