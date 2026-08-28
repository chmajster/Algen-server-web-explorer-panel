import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

describe("desktop dialog windowing", () => {
  it("can be dragged, resized, maximized and restored", () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1200 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });

    render(<Modal title="Edit Lab" onClose={vi.fn()}><p>Lab form</p></Modal>);
    const dialog = screen.getByRole("dialog", { name: "Edit Lab" });
    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue({
      x: 100, y: 80, left: 100, top: 80, right: 600, bottom: 480,
      width: 500, height: 400, toJSON: () => ({}),
    } as DOMRect);

    const titlebar = dialog.querySelector<HTMLElement>(".modal-header");
    expect(titlebar).not.toBeNull();
    fireEvent.pointerDown(titlebar as HTMLElement, { clientX: 160, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 260, clientY: 180 });
    fireEvent.pointerUp(window);

    expect(dialog.style.transform).toBe("none");
    expect(dialog.style.left).toBe("200px");
    expect(dialog.style.top).toBe("160px");
    expect(dialog.style.width).toBe("500px");
    expect(dialog.style.height).toBe("400px");

    const southEast = dialog.querySelector<HTMLElement>(".dialog-resize-se");
    expect(southEast).not.toBeNull();
    fireEvent.pointerDown(southEast as HTMLElement, { clientX: 700, clientY: 560 });
    fireEvent.pointerMove(window, { clientX: 800, clientY: 620 });
    fireEvent.pointerUp(window);
    expect(dialog.style.width).toBe("600px");
    expect(dialog.style.height).toBe("460px");

    fireEvent.click(screen.getByRole("button", { name: "Maximize Edit Lab" }));
    expect(dialog).toHaveClass("dialog-window-maximized");
    expect(dialog.style.left).toBe("8px");
    expect(dialog.style.top).toBe("8px");
    expect(dialog.style.width).toBe("1184px");
    expect(dialog.style.height).toBe("784px");
    expect(dialog.querySelector(".dialog-resize-se")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore Edit Lab" }));
    expect(dialog).not.toHaveClass("dialog-window-maximized");
    expect(dialog.style.left).toBe("200px");
    expect(dialog.style.top).toBe("160px");
    expect(dialog.style.width).toBe("600px");
    expect(dialog.style.height).toBe("460px");

    Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: originalHeight });
  });

  it("brings the clicked dialog in front of other modal windows", () => {
    render(<>
      <Modal title="Edit Lab" onClose={vi.fn()}><p>Edit form</p></Modal>
      <Modal title="Lab Settings" onClose={vi.fn()}><p>Settings form</p></Modal>
    </>);

    const editLab = screen.getByRole("dialog", { name: "Edit Lab" });
    const labSettings = screen.getByRole("dialog", { name: "Lab Settings" });
    const editLayer = editLab.closest<HTMLElement>(".dialog-window-layer");
    const settingsLayer = labSettings.closest<HTMLElement>(".dialog-window-layer");

    expect(editLayer).not.toBeNull();
    expect(settingsLayer).not.toBeNull();
    expect(Number(settingsLayer?.style.zIndex)).toBeGreaterThan(Number(editLayer?.style.zIndex));

    fireEvent.pointerDown(editLab, { clientX: 200, clientY: 160 });
    expect(Number(editLayer?.style.zIndex)).toBeGreaterThan(Number(settingsLayer?.style.zIndex));

    fireEvent.pointerDown(labSettings, { clientX: 240, clientY: 190 });
    expect(Number(settingsLayer?.style.zIndex)).toBeGreaterThan(Number(editLayer?.style.zIndex));
  });

  it("keeps maximized dialogs above the taskbar", () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1200 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });

    const desktop = document.createElement("div");
    desktop.className = "desktop";
    const taskbar = document.createElement("div");
    taskbar.className = "taskbar";
    desktop.appendChild(taskbar);
    document.body.appendChild(desktop);

    vi.spyOn(desktop, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 1200, bottom: 800,
      width: 1200, height: 800, toJSON: () => ({}),
    } as DOMRect);
    vi.spyOn(taskbar, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 740, left: 0, top: 740, right: 1200, bottom: 800,
      width: 1200, height: 60, toJSON: () => ({}),
    } as DOMRect);

    const result = render(<Modal title="Taskbar Safe" onClose={vi.fn()}><p>Form</p></Modal>);
    const dialog = screen.getByRole("dialog", { name: "Taskbar Safe" });

    fireEvent.click(screen.getByRole("button", { name: "Maximize Taskbar Safe" }));
    expect(dialog.style.left).toBe("8px");
    expect(dialog.style.top).toBe("8px");
    expect(dialog.style.width).toBe("1184px");
    expect(dialog.style.height).toBe("724px");

    result.unmount();
    desktop.remove();
    Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: originalHeight });
  });
});
