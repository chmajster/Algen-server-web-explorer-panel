import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadLanguage } from "../../i18n";

const loginMock = vi.hoisted(() => vi.fn());
vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, login: loginMock };
});

import { Login } from "./Login";

const user = { username: "alice", home: "/home/alice", csrf_token: "csrf" };

function fillCredentials(username = " alice ", password = "secret") {
  fireEvent.change(screen.getByLabelText("Linux user"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
}

describe("Login", () => {
  beforeEach(async () => {
    loginMock.mockReset();
    await loadLanguage("en-US");
  });

  it("submits the trimmed username and password", async () => {
    const onLogin = vi.fn();
    loginMock.mockResolvedValue(user);
    render(<Login language="en-US" onLogin={onLogin} />);

    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith("alice", "secret", false));
    expect(onLogin).toHaveBeenCalledWith(user);
    expect(screen.getByLabelText("Linux user")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });

  it("passes the remember-me checkbox to authentication", async () => {
    loginMock.mockResolvedValue(user);
    render(<Login language="en-US" onLogin={vi.fn()} />);
    fillCredentials();
    fireEvent.click(screen.getByLabelText("Remember me"));
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(loginMock).toHaveBeenCalledWith("alice", "secret", true));
  });

  it("shows an accessible loading state", async () => {
    let resolve!: (value: typeof user) => void;
    loginMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<Login language="en-US" onLogin={vi.fn()} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(document.querySelector(".login-spinner")).not.toBeNull();
    expect(document.querySelector(".login-panel")).toHaveAttribute("aria-busy", "true");
    resolve(user);
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
  });

  it("shows a translated compact alert for invalid credentials", async () => {
    loginMock.mockResolvedValue(user);
    render(<Login language="en-US" onLogin={() => { throw new Error("Invalid username"); }} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Invalid username or password");
    expect(alert).toHaveAttribute("aria-live", "polite");
  });

  it("toggles password visibility with an accessible button", () => {
    render(<Login language="en-US" onLogin={vi.fn()} />);
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
  });

  it("does not submit again while authentication is pending", async () => {
    let resolve!: (value: typeof user) => void;
    loginMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { container } = render(<Login language="en-US" onLogin={vi.fn()} />);
    fillCredentials();
    const form = container.querySelector("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(loginMock).toHaveBeenCalledTimes(1);
    resolve(user);
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
  });
});
