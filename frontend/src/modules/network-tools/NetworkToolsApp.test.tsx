import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { NetworkToolsApp } from "./NetworkToolsApp";

test("renders safe diagnostic form", () => {
  render(<NetworkToolsApp permissions={["network_tools.view", "network_tools.ping"]} toast={vi.fn()} />);
  expect(screen.getByText("Network Tools")).toBeInTheDocument();
  expect(screen.getByLabelText("Target")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
});
