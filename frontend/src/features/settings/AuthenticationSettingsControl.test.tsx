import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import authSettingsSource from "./AuthenticationSettingsControl.tsx?raw";
import { AuthenticationSettingsControl } from "./AuthenticationSettingsControl";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("../../core/api/transport", () => ({
  request: mocks.request,
}));

type AuthMode = "local" | "system";

type AuthSettings = {
  mode: AuthMode;
  configured_mode: AuthMode;
  restart_required: boolean;
  default_mode: "local";
  local_database_enabled: boolean;
  system_authentication_enabled: boolean;
  local_user_count: number;
  local_enabled_admin_count: number;
  reauthentication_required?: boolean;
};

const localSettings: AuthSettings = {
  mode: "local",
  configured_mode: "local",
  restart_required: false,
  default_mode: "local",
  local_database_enabled: true,
  system_authentication_enabled: false,
  local_user_count: 1,
  local_enabled_admin_count: 1,
  reauthentication_required: false,
};

const pendingSystemSettings: AuthSettings = {
  ...localSettings,
  configured_mode: "system",
  restart_required: true,
};

function mockRequests(initial: AuthSettings, putResult: AuthSettings = initial) {
  mocks.request.mockImplementation((url: string, options?: RequestInit) => {
    if (url === "/api/settings/authentication/local-users") {
      return Promise.resolve({ users: [] });
    }
    if (url === "/api/settings/authentication" && options?.method === "PUT") {
      return Promise.resolve(putResult);
    }
    if (url === "/api/settings/authentication") {
      return Promise.resolve(initial);
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

function renderControl(locale = "pl-PL") {
  render(
    <div data-testid="settings-root">
      <div className="settings-content" data-testid="settings-content" />
      <AuthenticationSettingsControl active locale={locale} toast={mocks.toast} />
    </div>,
  );
}

describe("authentication settings pending restart", () => {
  beforeEach(() => {
    mocks.request.mockReset();
    mocks.toast.mockReset();
  });

  it("changes configured mode without reload, logout or leaving Settings", async () => {
    mockRequests(localSettings, pendingSystemSettings);
    renderControl();

    const systemButton = await screen.findByRole("radio", { name: /PAM \+ LDAP/ });
    fireEvent.click(systemButton);

    const banner = await screen.findByTestId("auth-restart-required");
    expect(within(banner).getByText("Restart wymagany")).toBeInTheDocument();
    expect(within(banner).getByText("Metoda uwierzytelniania została zmieniona. Aby zastosować zmianę, wymagany jest restart aplikacji WebNAS.")).toBeInTheDocument();
    expect(screen.getByText("zostanie aktywowane po restarcie")).toBeInTheDocument();
    expect(systemButton).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /Local database/ })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("authentication-settings-card")).toBeInTheDocument();
    expect(screen.getByTestId("settings-root")).toBeInTheDocument();
    expect(mocks.request.mock.calls.some(([url]) => url === "/api/auth/logout")).toBe(false);
  });

  it("restores the persistent restart banner from a normal GET", async () => {
    mockRequests(pendingSystemSettings);
    renderControl();

    const banner = await screen.findByTestId("auth-restart-required");
    expect(banner).toHaveTextContent("Metoda uwierzytelniania została zmieniona z: Local database");
    expect(banner).toHaveTextContent("na: PAM + LDAP");
    expect(screen.getByRole("radio", { name: /PAM \+ LDAP/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Aktywne teraz")).toBeInTheDocument();
  });

  it("hides the banner when a pending change is cancelled before restart", async () => {
    mockRequests(pendingSystemSettings, localSettings);
    renderControl();

    await screen.findByTestId("auth-restart-required");
    const localButton = screen.getByRole("radio", { name: /Local database/ });
    fireEvent.click(localButton);

    await waitFor(() => expect(screen.queryByTestId("auth-restart-required")).not.toBeInTheDocument());
    expect(localButton).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText("zostanie aktywowane po restarcie")).not.toBeInTheDocument();
  });

  it("shows the required English restart message", async () => {
    mockRequests(pendingSystemSettings);
    renderControl("en-US");

    const banner = await screen.findByTestId("auth-restart-required");
    expect(within(banner).getByText("Restart required")).toBeInTheDocument();
    expect(within(banner).getByText("Authentication method changed. Restart the WebNAS application to apply the change.")).toBeInTheDocument();
    expect(screen.getByText("will be activated after restart")).toBeInTheDocument();
  });

  it("contains no automatic page reload or logout implementation", () => {
    expect(authSettingsSource).not.toContain("window.location.reload");
    expect(authSettingsSource).not.toContain("/api/auth/logout");
  });
});
