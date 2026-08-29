import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadLanguageWithFallback: vi.fn(),
}));

vi.mock("./i18n", () => ({
  detectLanguage: () => "en-US",
  loadLanguageWithFallback: mocks.loadLanguageWithFallback,
}));
vi.mock("./app/App", () => ({ App: () => <div>App</div> }));

describe("application bootstrap", () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.loadLanguageWithFallback.mockReset();
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("renders a recoverable retry state when the initial locale chunk cannot load", async () => {
    const error = new Error("locale chunk unavailable");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mocks.loadLanguageWithFallback.mockRejectedValue(error);

    await import("./main");

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("WebNAS could not load language resources.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalledWith("WebNAS bootstrap failed", error);
    consoleError.mockRestore();
  });
});
