import { afterEach, describe, expect, it, vi } from "vitest";
import { parseStoredStringArray, readStoredEnum, readStoredNumber, readStorageValue, removeStorageValue, writeStorageValue } from "./persistence";

afterEach(() => vi.restoreAllMocks());

describe("persistent UI state boundaries", () => {
  it("rejects malformed and wrong-shaped string arrays", () => {
    expect(parseStoredStringArray("{" )).toEqual([]);
    expect(parseStoredStringArray('{"path":"/tmp"}')).toEqual([]);
    expect(parseStoredStringArray('["/a", 7, "", "/b"]')).toEqual(["/a", "/b"]);
  });

  it("rejects unknown enum values", () => {
    expect(readStoredEnum("broken", ["list", "medium", "large"] as const, "list")).toBe("list");
    expect(readStoredEnum("medium", ["list", "medium", "large"] as const, "list")).toBe("medium");
  });

  it("clamps finite persisted numbers and rejects NaN/infinity", () => {
    expect(readStoredNumber("999", 238, 180, 420)).toBe(420);
    expect(readStoredNumber("-10", 238, 180, 420)).toBe(180);
    expect(readStoredNumber("NaN", 238, 180, 420)).toBe(238);
    expect(readStoredNumber("Infinity", 238, 180, 420)).toBe(238);
  });

  it("degrades safely when browser storage reads are blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(readStorageValue("webnas_theme")).toBeNull();
    expect(readStorageValue("webnas_theme", "session")).toBeNull();
  });

  it("degrades safely when browser storage writes or removals fail", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
    expect(writeStorageValue("webnas_theme", "dark")).toBe(false);
    expect(writeStorageValue("webnas_theme", "dark", "session")).toBe(false);
    expect(removeStorageValue("webnas_theme")).toBe(false);
    expect(removeStorageValue("webnas_theme", "session")).toBe(false);
  });
});
