import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import type { BackgroundAction } from "./types";
import { ActionsCenter } from "./ActionsCenter";

const running: BackgroundAction = {
  key: "module:running",
  id: "running",
  source: "module",
  title: "Install Samba",
  subtitle: "Samba",
  status: "running",
  progress: 42,
  currentStep: "Installing packages",
  createdAt: Date.now(),
  target: { app: "module", moduleId: "samba", jobId: "running", detailType: "package-job" },
};

const failed: BackgroundAction = {
  key: "hosts:failed",
  id: "failed",
  source: "hosts",
  title: "Update host",
  status: "failed",
  error: "Connection refused",
  createdAt: Date.now(),
  target: { app: "hosts", entityId: "failed", detailType: "hosts-operation" },
};

describe("ActionsCenter", () => {
  it("opens exact details and only allows terminal actions to be dismissed", () => {
    const onOpen = vi.fn();
    const onDismiss = vi.fn();
    const triggerRef = createRef<HTMLButtonElement>();
    render(
      <>
        <button ref={triggerRef}>Actions</button>
        <ActionsCenter
          actions={[failed, running]}
          locale="en-US"
          t={(key) => key}
          triggerRef={triggerRef}
          onOpen={onOpen}
          onDismiss={onDismiss}
          onClose={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "actions.openDetails: Install Samba" }));
    expect(onOpen).toHaveBeenCalledWith(running);
    expect(screen.queryByRole("button", { name: "actions.dismiss: Install Samba" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "actions.dismiss: Update host" }));
    expect(onDismiss).toHaveBeenCalledWith("hosts:failed");
  });

  it("closes on Escape and outside click, then returns focus to its trigger", () => {
    const onClose = vi.fn();
    const triggerRef = createRef<HTMLButtonElement>();
    render(<button ref={triggerRef}>Actions</button>);
    const view = render(
      <ActionsCenter
        actions={[]}
        locale="en-US"
        t={(key) => key}
        triggerRef={triggerRef}
        onOpen={vi.fn()}
        onDismiss={vi.fn()}
        onClose={onClose}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(2);

    view.unmount();
    expect(triggerRef.current).toHaveFocus();
  });
});
