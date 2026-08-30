import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { SecurityCenterApp } from "./SecurityCenterApp";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.endsWith("/summary") ? { score: 92, findings: 1, last_scan: 1, severity: { critical: 0, high: 0 }, areas: {}, metrics: {} } : { items: [], total: 0 };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});

test("renders security score", async () => {
  render(<SecurityCenterApp permissions={["security.view"]} language="en-US" toast={vi.fn()} />);
  expect(await screen.findByText("Security Center")).toBeInTheDocument();
  expect(await screen.findByText("92/100")).toBeInTheDocument();
});
