import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadLanguage } from "../i18n";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  settingsMe: vi.fn(),
  tasks: vi.fn(),
  allTasks: vi.fn(),
  updateProgress: vi.fn(),
  updatePublicProgress: vi.fn(),
  updateCompletion: vi.fn(),
  loadLanguageWithFallback: vi.fn(),
  authRequest: vi.fn(),
  authMe: vi.fn(),
  resetAuthenticationState: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    login: mocks.login,
    me: mocks.me,
    api: {
      ...actual.api,
      settingsMe: mocks.settingsMe,
      tasks: mocks.tasks,
      allTasks: mocks.allTasks,
      updateProgress: mocks.updateProgress,
      updatePublicProgress: mocks.updatePublicProgress,
      updateCompletion: mocks.updateCompletion,
    },
  };
});

vi.mock("../i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../i18n")>();
  return {
    ...actual,
    loadLanguageWithFallback: mocks.loadLanguageWithFallback,
  };
});

vi.mock("../core/api/transport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../core/api/transport")>();
  return {
    ...actual,
    request: mocks.authRequest,
    me: mocks.authMe,
    resetAuthenticationState: mocks.resetAuthenticationState,
  };
});

vi.mock("./Desktop", () => ({ Desktop: ({ language }: { language: string }) => <div data-testid="desktop">{language}</div> }));
vi.mock("../features/connection/ConnectionStatusMonitor", () => ({ ConnectionStatusMonitor: ({ onRestored }: { onRestored: () => void }) => <button data-testid="connection-restored" onClick={onRestored}>restored</button> }));
vi.mock("../features/transfers/useUploadManager", () => ({
  useUploadManager: () => ({ tasks: [], controls: {} }),
}));

import { Login } from "../features/auth/Login";
import { App } from "./App";

const user = { username: "alice", home: "/home/alice", csrf_token: "csrf" };
const profile = {
  ...user,
  language: "pl-PL",
  theme: "system",
  permissions: [],
  notification_auto_hide: true,
};
const idleUpdate = { state: "idle", running: false, pid: null, exit_code: null, started_at: null, finished_at: null, log: "", lines: [] };

describe("authentication initialization", () => {
  beforeEach(async () => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    window.history.replaceState({}, "", "/");
    sessionStorage.removeItem("webnas_completed_update_reload");
    localStorage.removeItem("webnas_language");
    mocks.settingsMe.mockResolvedValue(profile);
    mocks.tasks.mockResolvedValue([]);
    mocks.allTasks.mockResolvedValue([]);
    mocks.updateProgress.mockResolvedValue(idleUpdate);
    mocks.updatePublicProgress.mockResolvedValue(idleUpdate);
    mocks.updateCompletion.mockResolvedValue({ notice: null });
    mocks.loadLanguageWithFallback.mockImplementation(async (language) => language);
    mocks.authRequest.mockResolvedValue({
      mode: "system",
      local_enabled: false,
      pam_enabled: true,
      ldap_enabled: false,
      available_providers: ["pam"],
      default_provider: "pam",
    });
    mocks.authMe.mockResolvedValue(user);
    await loadLanguage("pl-PL");
  });

  it("passes the selected remember-me option to authentication", async () => {
    const onLogin = vi.fn();
    mocks.authRequest
      .mockResolvedValueOnce({ mode: "system", local_enabled: false, pam_enabled: true, ldap_enabled: false, available_providers: ["pam"], default_provider: "pam" })
      .mockResolvedValueOnce({ username: "alice", home: "/home/alice", csrf_token: "csrf", auth_provider: "pam" });
    render(<Login language="pl-PL" onLogin={onLogin} />);

    const username = await screen.findByLabelText("Użytkownik Linux");
    fireEvent.change(username, { target: { value: " alice " } });
    fireEvent.change(screen.getByLabelText("Hasło"), { target: { value: "secret" } });
    fireEvent.click(screen.getByLabelText("Zapamiętaj mnie"));
    fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

    await waitFor(() => expect(mocks.authRequest).toHaveBeenCalledTimes(2));
    const loginOptions = mocks.authRequest.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(loginOptions.body))).toMatchObject({
      username: "alice", password: "secret", remember_me: true, auth_method: "pam",
    });
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(expect.objectContaining({ username: "alice" })));
  });

  it("adds error space only after authentication fails", async () => {
    mocks.authRequest
      .mockResolvedValueOnce({ mode: "system", local_enabled: false, pam_enabled: true, ldap_enabled: false, available_providers: ["pam"], default_provider: "pam" })
      .mockRejectedValueOnce(Object.assign(new Error("Unauthorized"), { status: 401 }));
    const { container } = render(<Login language="pl-PL" onLogin={vi.fn()} />);

    expect(container.querySelector(".login-error")).toBeNull();
    const username = await screen.findByLabelText("Użytkownik Linux");
    fireEvent.change(username, { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Hasło"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nieprawidłowa nazwa użytkownika lub hasło");
  });

  it("does not render Login or Desktop while the initial session check is pending", () => {
    mocks.me.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<App />);

    expect(container.querySelector(".boot-screen")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Zaloguj się" })).toBeNull();
    expect(screen.queryByTestId("desktop")).toBeNull();
  });

  it("restores a valid remembered session before mounting the protected UI", async () => {
    mocks.me.mockResolvedValue(user);
    render(<App />);

    expect(screen.queryByRole("button", { name: "Zaloguj się" })).toBeNull();
    expect(await screen.findByTestId("desktop")).toBeInTheDocument();
    expect(mocks.settingsMe).toHaveBeenCalled();
  });

  it("shows Login only after the initial session check reports an anonymous user", async () => {
    mocks.me.mockRejectedValue(new Error("Authentication required"));
    render(<App />);

    await waitFor(() => expect(document.querySelector(".login-panel button[type='submit']")).not.toBeNull());
    expect(screen.queryByTestId("desktop")).toBeNull();
  });

  it("keeps the loading gate under React StrictMode", () => {
    mocks.me.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<StrictMode><App /></StrictMode>);

    expect(container.querySelector(".boot-screen")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Zaloguj się" })).toBeNull();
    expect(screen.queryByTestId("desktop")).toBeNull();
  });

  it("ignores a stale locale load that resolves after a newer activation", async () => {
    let resolvePolish: ((value: "pl-PL") => void) | undefined;
    let resolveEnglish: ((value: "en-US") => void) | undefined;
    mocks.me.mockResolvedValue(user);
    mocks.settingsMe
      .mockResolvedValueOnce(profile)
      .mockResolvedValueOnce({ ...profile, language: "en-US" });
    mocks.loadLanguageWithFallback.mockImplementation((language) => new Promise((resolve) => {
      if (language === "pl-PL") resolvePolish = resolve;
      else resolveEnglish = resolve;
    }));

    render(<App />);
    expect(await screen.findByTestId("desktop")).toHaveTextContent("en-US");
    await waitFor(() => expect(mocks.loadLanguageWithFallback).toHaveBeenCalledWith("pl-PL"));

    fireEvent.click(screen.getByTestId("connection-restored"));
    await waitFor(() => expect(mocks.loadLanguageWithFallback).toHaveBeenCalledWith("en-US"));
    resolveEnglish?.("en-US");
    await waitFor(() => expect(screen.getByTestId("desktop")).toHaveTextContent("en-US"));
    expect(localStorage.getItem("webnas_language")).toBe("en-US");

    resolvePolish?.("pl-PL");
    await Promise.resolve();
    expect(screen.getByTestId("desktop")).toHaveTextContent("en-US");
    expect(localStorage.getItem("webnas_language")).toBe("en-US");
  });

  it("reloads once after a successful system update", async () => {
    const reloadPage = vi.fn();
    window.history.replaceState({}, "", "/update-status");
    mocks.me.mockResolvedValue(user);
    mocks.settingsMe.mockResolvedValue({ ...profile, permissions: ["updates.view"] });
    mocks.updateProgress.mockResolvedValue({
      ...idleUpdate,
      id: "update-success-1",
      state: "completed",
      exit_code: 0,
      finished_at: 200,
    });

    const { rerender } = render(<App reloadPage={reloadPage} />);

    await waitFor(() => expect(reloadPage).toHaveBeenCalledOnce());
    expect(window.location.pathname).toBe("/");
    expect(sessionStorage.getItem("webnas_completed_update_reload")).toBe("update-success-1");

    rerender(<App reloadPage={reloadPage} />);
    expect(reloadPage).toHaveBeenCalledOnce();
  });

  it("does not reload after a failed system update", async () => {
    const reloadPage = vi.fn();
    window.history.replaceState({}, "", "/update-status");
    mocks.me.mockResolvedValue(user);
    mocks.settingsMe.mockResolvedValue({ ...profile, permissions: ["updates.view"] });
    mocks.updateProgress.mockResolvedValue({
      ...idleUpdate,
      id: "update-failed-1",
      state: "failed",
      exit_code: 1,
      finished_at: 200,
    });

    render(<App reloadPage={reloadPage} />);

    await waitFor(() => expect(document.querySelector(".update-status-page.failed")).toBeInTheDocument());
    expect(reloadPage).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/update-status");
  });
});
