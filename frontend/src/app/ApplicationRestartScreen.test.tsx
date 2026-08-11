import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApplicationRestartScreen } from "./ApplicationRestartScreen";

describe("ApplicationRestartScreen", () => {
  it("shows a clear restart state and elapsed time", () => {
    render(<ApplicationRestartScreen elapsedSeconds={125} t={(key) => key} />);

    expect(screen.getByRole("status", { name: "updateStatus.phase.restarting" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "updateStatus.phase.restarting" })).toBeInTheDocument();
    expect(screen.getByText("connection.reconnecting")).toBeInTheDocument();
    expect(screen.getByText("2 min 05 s")).toBeInTheDocument();
  });
});
