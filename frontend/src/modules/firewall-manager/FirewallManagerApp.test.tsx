import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { FirewallManagerApp } from "./FirewallManagerApp";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.endsWith("/status") ? { backend: "ufw", available_backends: ["ufw"], active: true, detail: "Status: active", rules: 0 } : { items: [], total: 0 };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});

test("renders firewall dashboard", async () => {
  render(<FirewallManagerApp permissions={["firewall.view"]} language="en-US" toast={vi.fn()} />);
  expect(await screen.findByText("Firewall Manager")).toBeInTheDocument();
  expect((await screen.findAllByText("ufw")).length).toBeGreaterThan(0);
});
