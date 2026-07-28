import { describe, expect, it } from "vitest";
import {
  INTERFACE_SCALE_DEFAULT,
  INTERFACE_SCALE_MAX,
  INTERFACE_SCALE_MIN,
  interfaceScaleFactor,
  normalizeInterfaceScale,
} from "./interfaceScale";

describe("interface scale normalization", () => {
  it.each([
    [50, 50],
    [75, 75],
    [100, 100],
    [125, 125],
    [175, 175],
    [200, 200],
  ])("keeps the supported percentage %s", (input, expected) => {
    expect(normalizeInterfaceScale(input)).toBe(expected);
  });

  it("clamps out-of-range values and defaults invalid values", () => {
    expect(normalizeInterfaceScale(0)).toBe(INTERFACE_SCALE_MIN);
    expect(normalizeInterfaceScale(500)).toBe(INTERFACE_SCALE_MAX);
    expect(normalizeInterfaceScale("not-a-scale")).toBe(INTERFACE_SCALE_DEFAULT);
    expect(normalizeInterfaceScale(Number.NaN)).toBe(INTERFACE_SCALE_DEFAULT);
  });

  it("converts stored percentages to layout factors explicitly", () => {
    expect(interfaceScaleFactor(75)).toBe(0.75);
    expect(interfaceScaleFactor(100)).toBe(1);
    expect(interfaceScaleFactor(125)).toBe(1.25);
    expect(interfaceScaleFactor(200)).toBe(2);
  });
});
