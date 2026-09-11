import { describe, expect, it } from "vitest";
import { parseStoredStringArray, readStoredEnum, readStoredNumber } from "./persistence";

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
});
