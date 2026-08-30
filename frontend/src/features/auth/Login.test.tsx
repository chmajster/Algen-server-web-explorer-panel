import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Login } from "./Login";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  me: vi.fn(),
  resetAuthenticationState: vi.fn(),
}));

vi.mock("../../core/api/transport", () => ({
  request: mocks.request,
  me: mocks.me,
  resetAuthenticationState: mocks.resetAuthenticationState,
}));

vi.mock("../../i18n", () => ({
  translate: (_language: string, key: string) => key,
}));

describe("authentication mode selection", () => {
  beforeEach(() => {
    mocks.request.mockReset();
    mocks.me.mockReset();
    mocks.resetAuthenticationState.mockReset();
    mocks.me.mockResolvedValue({ username: "alice", home: "/tmp/alice", csrf_token: "csrf" });
  });

  it("uses local database login by default without a provider selector", async () => {
    mocks.request
      .mockResolvedValueOnce({
        mode: "local",
        local_enabled: true,
        pam_enabled: false,
        ldap_enabled: false,
        available_providers: ["local"],
        default_provider: "local",
      })
      .mockResolvedValueOnce({
        username: "admin",
        home: "/var/lib/webnas/local-homes/admin",
        csrf_token: "csrf",
        auth_provider: "local",
      });

    render(<Login language="en-US" onLogin={vi.fn()} />);

    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith("/api/auth/config", { cache: "no-store" }));
    expect(screen.queryByRole("combobox", { name: "Authentication method" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("auth.password"), { target: { value: "local-secret" } });
    fireEvent.submit(screen.getByRole("button", { name: "auth.signIn" }).closest("form")!);

    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(2));
    const loginOptions = mocks.request.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(loginOptions.body))).toMatchObject({
      username: "admin",
      password: "local-secret",
      auth_method: "local",
    });
  });

  it("keeps the PAM-only form in system mode when LDAP is disabled", async () => {
    mocks.request.mockResolvedValueOnce({
      mode: "system",
      local_enabled: false,
      pam_enabled: true,
      ldap_enabled: false,
      available_providers: ["pam"],
      default_provider: "pam",
    });

    render(<Login language="en-US" onLogin={vi.fn()} />);

    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith("/api/auth/config", { cache: "no-store" }));
    expect(screen.queryByRole("combobox", { name: "Authentication method" })).not.toBeInTheDocument();
  });

  it("selects LDAP by default in system mode and sends the explicit provider", async () => {
    mocks.request
      .mockResolvedValueOnce({
        mode: "system",
        local_enabled: false,
        pam_enabled: true,
        ldap_enabled: true,
        available_providers: ["ldap", "pam"],
        default_provider: "ldap",
      })
      .mockResolvedValueOnce({
        username: "alice",
        home: "/home/alice",
        csrf_token: "csrf",
        auth_provider: "ldap",
      });
    const onLogin = vi.fn();

    render(<Login language="en-US" onLogin={onLogin} />);

    const provider = await screen.findByRole("combobox", { name: "Authentication method" });
    expect(provider).toHaveValue("ldap");

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("auth.password"), { target: { value: "secret" } });
    fireEvent.submit(screen.getByRole("button", { name: "auth.signIn" }).closest("form")!);

    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(2));
    const loginOptions = mocks.request.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(loginOptions.body))).toMatchObject({
      username: "alice",
      password: "secret",
      auth_method: "ldap",
    });
    await waitFor(() => expect(onLogin).toHaveBeenCalled());
  });

  it("keeps PAM selected after a failed PAM login and never retries LDAP", async () => {
    mocks.request
      .mockResolvedValueOnce({
        mode: "system",
        local_enabled: false,
        pam_enabled: true,
        ldap_enabled: true,
        available_providers: ["ldap", "pam"],
        default_provider: "ldap",
      })
      .mockRejectedValueOnce(Object.assign(new Error("Invalid username or password"), { status: 401 }));

    render(<Login language="en-US" onLogin={vi.fn()} />);

    const provider = await screen.findByRole("combobox", { name: "Authentication method" });
    fireEvent.change(provider, { target: { value: "pam" } });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "root" } });
    fireEvent.change(screen.getByLabelText("auth.password"), { target: { value: "bad" } });
    fireEvent.submit(screen.getByRole("button", { name: "auth.signIn" }).closest("form")!);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(provider).toHaveValue("pam");
    expect(mocks.request).toHaveBeenCalledTimes(2);
    const loginOptions = mocks.request.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(loginOptions.body)).auth_method).toBe("pam");
    expect(mocks.me).not.toHaveBeenCalled();
  });
});
