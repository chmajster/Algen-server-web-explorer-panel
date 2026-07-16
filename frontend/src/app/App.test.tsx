import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const loginMock = vi.hoisted(() => vi.fn());

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  login: loginMock,
}));

import { Login } from "./App";

describe("Login", () => {
  beforeEach(() => loginMock.mockReset());

  it("passes the selected remember-me option to authentication", async () => {
    const onLogin = vi.fn();
    loginMock.mockResolvedValue({ username: "alice", home: "/home/alice", csrf_token: "csrf" });
    render(<Login language="pl-PL" onLogin={onLogin} />);

    fireEvent.change(screen.getByLabelText("Użytkownik Linux"), { target: { value: " alice " } });
    fireEvent.change(screen.getByLabelText("Hasło"), { target: { value: "secret" } });
    fireEvent.click(screen.getByLabelText("Zapamiętaj mnie"));
    fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith("alice", "secret", true));
    expect(onLogin).toHaveBeenCalledWith(expect.objectContaining({ username: "alice" }));
  });
});
