import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import policyControlSource from "./UpdateDetailsPolicyControl.tsx?raw";
import { UpdateDetailsPolicyControl } from "./UpdateDetailsPolicyControl";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("../../core/api/transport", () => ({
  request: mocks.request,
}));

const t = (key: string) => key;

function renderControl() {
  render(
    <>
      <div data-testid="outside-settings" />
      <div data-testid="settings-root">
        <section className="settings-content policy-content">
          <section className="policy-browser">
            <aside className="policy-groups">
              <button className="active" type="button">updates</button>
              <button type="button">containers</button>
            </aside>
            <section className="policy-list" data-testid="policy-list">
              <header><b>5</b></header>
              <button type="button">base policy</button>
            </section>
          </section>
        </section>
        <UpdateDetailsPolicyControl active t={t} toast={mocks.toast} />
      </div>
    </>,
  );
}

describe("update details policy control", () => {
  beforeEach(() => {
    document.documentElement.lang = "pl-PL";
    mocks.request.mockReset();
    mocks.toast.mockReset();
    mocks.request.mockResolvedValue({
      policy_id: "updates.detailed_steps",
      detailed_steps: false,
      default_detailed_steps: false,
    });
  });

  it("keeps the policy observer scoped to Settings and does not enter a mutation feedback loop", async () => {
    renderControl();

    const list = screen.getByTestId("policy-list");
    expect(await within(list).findByRole("button", { name: /Szczegółowe kroki aktualizacji/ })).toBeInTheDocument();
    await waitFor(() => expect(within(list).getByText("6")).toBeInTheDocument());
    expect(within(list).getAllByRole("button")).toHaveLength(2);

    const unrelated = document.createElement("div");
    unrelated.textContent = "outside mutation";
    screen.getByTestId("outside-settings").appendChild(unrelated);
    await Promise.resolve();

    expect(within(list).getAllByRole("button")).toHaveLength(2);
    expect(within(list).getByText("6")).toBeInTheDocument();
    expect(policyControlSource).not.toContain("observer.observe(document.body");
    expect(policyControlSource).toContain("observer.observe(root");
  });

  it("restores the original policy count when the Updates group is no longer active", async () => {
    renderControl();

    const list = screen.getByTestId("policy-list");
    await within(list).findByRole("button", { name: /Szczegółowe kroki aktualizacji/ });
    await waitFor(() => expect(within(list).getByText("6")).toBeInTheDocument());

    const updateGroup = within(screen.getByTestId("settings-root")).getByRole("button", { name: "updates" });
    updateGroup.classList.remove("active");

    await waitFor(() => expect(within(list).queryByRole("button", { name: /Szczegółowe kroki aktualizacji/ })).not.toBeInTheDocument());
    expect(within(list).getByText("5")).toBeInTheDocument();
  });
});
