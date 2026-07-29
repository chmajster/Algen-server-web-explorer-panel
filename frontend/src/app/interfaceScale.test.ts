import { describe, expect, it } from "vitest";
import {
  ALLOWED_UI_SCALES,
  INTERFACE_SCALE_DEFAULT,
  INTERFACE_SCALE_OPTIONS,
  interfaceScaleFactor,
  migrateLegacyInterfaceScale,
  normalizeInterfaceScale,
} from "./interfaceScale";

describe("interface scale normalization", () => {
  it.each([
    [80, 80],
    [90, 90],
    [100, 100],
    [110, 110],
    [125, 125],
  ])("keeps the supported percentage %s", (input, expected) => {
    expect(normalizeInterfaceScale(input)).toBe(expected);
  });

  it("accepts scale factors and exposes matching percentage options", () => {
    expect(ALLOWED_UI_SCALES.map((value) => normalizeInterfaceScale(value))).toEqual([...INTERFACE_SCALE_OPTIONS]);
  });

  it("migrates legacy percentages to the closest supported value", () => {
    expect(normalizeInterfaceScale(75)).toBe(80);
    expect(normalizeInterfaceScale(115)).toBe(110);
    expect(normalizeInterfaceScale(175)).toBe(125);
  });

  it("defaults out-of-range and invalid values", () => {
    expect(normalizeInterfaceScale(0)).toBe(INTERFACE_SCALE_DEFAULT);
    expect(normalizeInterfaceScale(500)).toBe(INTERFACE_SCALE_DEFAULT);
    expect(normalizeInterfaceScale("not-a-scale")).toBe(INTERFACE_SCALE_DEFAULT);
    expect(normalizeInterfaceScale(Number.NaN)).toBe(INTERFACE_SCALE_DEFAULT);
  });

  it("converts stored percentages to layout factors explicitly", () => {
    expect(interfaceScaleFactor(80)).toBe(0.8);
    expect(interfaceScaleFactor(90)).toBe(0.9);
    expect(interfaceScaleFactor(100)).toBe(1);
    expect(interfaceScaleFactor(110)).toBe(1.1);
    expect(interfaceScaleFactor(125)).toBe(1.25);
  });

  it("folds the legacy larger-text preference into interface scale", () => {
    expect(migrateLegacyInterfaceScale(100, false)).toBe(100);
    expect(migrateLegacyInterfaceScale(100, true)).toBe(110);
    expect(migrateLegacyInterfaceScale(90, true)).toBe(100);
    expect(migrateLegacyInterfaceScale(125, true)).toBe(125);
  });
});
