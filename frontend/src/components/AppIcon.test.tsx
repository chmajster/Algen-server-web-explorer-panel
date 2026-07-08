import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppIcon } from "./AppIcon";

describe("AppIcon", () => {
  it("renders an app launcher button", () => {
    const onOpen = vi.fn();

    render(<AppIcon label="File Manager" icon={<span aria-hidden="true">FM</span>} onOpen={onOpen} />);

    expect(screen.getByRole("button", { name: /file manager/i })).toBeInTheDocument();
  });
});
