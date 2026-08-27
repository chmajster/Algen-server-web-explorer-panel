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
});
