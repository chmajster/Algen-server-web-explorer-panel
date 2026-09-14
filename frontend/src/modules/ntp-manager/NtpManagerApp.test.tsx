import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { confirmDialog } from "../../components/DialogService";
import { ntpManagerClient, type NtpConfiguration, type NtpDiagnostics } from "./api/client";
import { NtpManagerApp } from "./NtpManagerApp";
import { backendLabel, firewallLabel, formatTimestamp, modeLabel, syncPresentation } from "./presentation";

vi.mock("../../components/DialogService", () => ({ confirmDialog: vi.fn() }));
vi.mock("./api/client", () => ({ ntpManagerClient: {
  dashboard: vi.fn(), config: vi.fn(), clients: vi.fn(), history: vi.fn(), backups: vi.fn(), timezones: vi.fn(),
  add: vi.fn(), update: vi.fn(), remove: vi.fn(), replaceSources: vi.fn(), test: vi.fn(), saveConfig: vi.fn(),
  sync: vi.fn(), service: vi.fn(), setTimezone: vi.fn(), diagnostics: vi.fn(), openFirewall: vi.fn(), installChrony: vi.fn(), restoreBackup: vi.fn(),
} }));

const config: NtpConfiguration = {
  mode: "client_server", sources: [{ server: "time.example.org", kind: "server", enabled: true }], allowed_networks: [],
  local_time_when_unsynced: false, local_stratum: 10, backend: "chrony", managed_path: "/etc/chrony/chrony.conf", unmanaged_config_detected: false,
};
const data: NtpDiagnostics = {
  backend: "chrony", available: true, role: "client_server", synchronized: true, timezone: "Europe/Warsaw", system_time: 1700000000,
  source: "time.example.org", offset: "0 ms", stratum: 2, reachability: "377", jitter: "0.01 ms", service: "chrony", service_state: "active", enabled: true,
  health: "healthy", metrics: {}, sources: [{ ...config.sources[0], selected: true, state: "selected", reach: 377, stratum: 2 }],
  summary: { source_count: 1, selected_count: 1, reachable_count: 1, client_count: 0 },
  firewall: { backend: "ufw", status: "unknown", managed_by_webnas: false }, warnings: [], collected_at: 1700000000,
};
const permissions = ["ntp.view", "ntp.manage", "ntp.sync", "ntp.service.control", "ntp.firewall.manage"];
const toast = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(confirmDialog).mockResolvedValue(true);
  vi.mocked(ntpManagerClient.dashboard).mockResolvedValue(data);
  vi.mocked(ntpManagerClient.config).mockResolvedValue(config);
  vi.mocked(ntpManagerClient.clients).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ntpManagerClient.history).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ntpManagerClient.backups).mockResolvedValue({ items: [] });
  vi.mocked(ntpManagerClient.timezones).mockResolvedValue({ items: ["Europe/Warsaw", "UTC"], total: 2 });
  vi.mocked(ntpManagerClient.diagnostics).mockResolvedValue({ ...data, checks: [{ code: "service", status: "PASS", detail: "Usługa działa" }] });
});
afterEach(cleanup);

function open(section: string) {
  fireEvent.click(within(screen.getByRole("navigation", { name: "Sekcje NTP Manager" })).getByRole("button", { name: new RegExp(section) }));
}
async function mount(allowed = permissions) {
  render(<NtpManagerApp permissions={allowed} language="pl" toast={toast} />);
  await screen.findByRole("heading", { name: "Czas zsynchronizowany" });
}

describe("NTP Manager workspace", () => {
  it("does not report missing synchronization while the initial request is pending", () => {
    vi.mocked(ntpManagerClient.dashboard).mockReturnValue(new Promise(() => {}));
    render(<NtpManagerApp permissions={permissions} language="pl" toast={toast} />);
    expect(screen.getByRole("status")).toHaveTextContent("Wczytywanie stanu NTP");
    expect(screen.queryByText("Brak synchronizacji")).not.toBeInTheDocument();
    expect(screen.queryByText("Usługa NTP niedostępna")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Synchronizuj teraz" })).toBeDisabled();
  });

  it("shows an explicit fetch error and supports retry rather than invented zero metrics", async () => {
    vi.mocked(ntpManagerClient.dashboard).mockRejectedValueOnce(new Error("Brak połączenia"));
    render(<NtpManagerApp permissions={permissions} language="pl" toast={toast} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Brak połączenia");
    expect(screen.queryByText("Brak synchronizacji")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByRole("heading", { name: "Czas zsynchronizowany" })).toBeInTheDocument();
  });

  it("renders shared metric cards, a selected navigation item and readable unknown states", async () => {
    await mount();
    expect(screen.getByText("Odchylenie zegara")).toBeInTheDocument();
    expect(screen.getByText("0 ms")).toBeInTheDocument();
    expect(screen.getByText("Niezweryfikowany")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przegląd" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
    open("Źródła czasu");
    expect(screen.getByRole("table", { name: "Źródła czasu NTP" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przegląd" })).not.toHaveAttribute("aria-current");
  });

  it("keeps identifiers available in full instead of hiding long source names", async () => {
    const host = "ntp-primary.very-long-infrastructure-name.example.internal";
    vi.mocked(ntpManagerClient.dashboard).mockResolvedValue({ ...data, sources: [{ server: host, selected: true }], source: host });
    vi.mocked(ntpManagerClient.config).mockResolvedValue({ ...config, sources: [{ server: host }] });
    await mount();
    expect(screen.getAllByText(host)).toHaveLength(2);
  });

  it("retains the source form after a rejected addition", async () => {
    vi.mocked(ntpManagerClient.add).mockRejectedValue(new Error("Niepoprawny adres"));
    await mount(); open("Źródła czasu");
    fireEvent.change(screen.getByLabelText("Adres źródła NTP"), { target: { value: "broken.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj źródło" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Niepoprawny adres", "error", "admin", "ntp-manager"));
    expect(screen.getByLabelText("Adres źródła NTP")).toHaveValue("broken.example");
  });

  it("keeps unsaved server settings during a status refresh and sends the original API payload", async () => {
    await mount(); open("Serwer NTP");
    fireEvent.change(screen.getByLabelText("Tryb NTP"), { target: { value: "client" } });
    fireEvent.click(screen.getByRole("button", { name: "Odśwież" }));
    await waitFor(() => expect(ntpManagerClient.dashboard).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Odśwież" })).toBeEnabled());
    expect(screen.getByLabelText("Tryb NTP")).toHaveValue("client");
    expect(screen.getByText("Masz niezapisane zmiany")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz konfigurację serwera" }));
    await waitFor(() => expect(ntpManagerClient.saveConfig).toHaveBeenCalledWith({
      mode: "client", sources: [{ server: "time.example.org", kind: "server", prefer: false, enabled: true, confirm: false }],
      allowed_networks: [], local_time_when_unsynced: false, local_stratum: 10,
    }));
  });

  it("preserves source editing, ordering controls and the update endpoint", async () => {
    await mount(); open("Źródła czasu");
    expect(screen.getByRole("button", { name: "Przesuń time.example.org w górę" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    fireEvent.change(screen.getByLabelText("Edytuj serwer NTP"), { target: { value: "time2.example.org" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz", exact: true }));
    await waitFor(() => expect(ntpManagerClient.update).toHaveBeenCalledWith("time.example.org", expect.objectContaining({ server: "time2.example.org", kind: "server", enabled: true })));
  });

  it("keeps mutation controls unavailable without their permissions", async () => {
    await mount(["ntp.view"]);
    expect(screen.queryByRole("button", { name: "Synchronizuj teraz" })).not.toBeInTheDocument();
    open("Źródła czasu");
    expect(screen.queryByRole("button", { name: "Dodaj źródło" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edytuj" })).not.toBeInTheDocument();
    open("Serwer NTP");
    expect(screen.getByLabelText("Tryb NTP")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Otwórz UDP/123" })).not.toBeInTheDocument();
    open("Konfiguracja");
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("gives the missing-service state a configuration path and disables synchronization", async () => {
    vi.mocked(ntpManagerClient.dashboard).mockResolvedValue({ ...data, available: false, synchronized: false, backend: "none", role: "disabled", health: "unavailable" });
    vi.mocked(ntpManagerClient.config).mockResolvedValue({ ...config, backend: "none" });
    render(<NtpManagerApp permissions={permissions} language="pl" toast={toast} />);
    await screen.findByRole("heading", { name: "Usługa NTP niedostępna" });
    expect(screen.getByRole("button", { name: "Synchronizuj teraz" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Przejdź do konfiguracji" }));
    expect(screen.getByRole("button", { name: "Zainstaluj Chrony" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("distinguishes an optional API failure from an empty client list", async () => {
    vi.mocked(ntpManagerClient.clients).mockRejectedValue(new Error("HTTP 503"));
    await mount(); open("Klienci");
    expect(screen.getByText("Nie udało się pobrać klientów")).toBeInTheDocument();
    expect(screen.queryByText("Brak klientów NTP")).not.toBeInTheDocument();
  });

  it("exposes useful empty states for clients, history and backups", async () => {
    await mount(); open("Klienci");
    expect(screen.getByText("Brak klientów NTP")).toBeInTheDocument();
    open("Historia"); expect(screen.getByText("Brak pomiarów w historii")).toBeInTheDocument();
    open("Konfiguracja"); expect(screen.getByText("Brak kopii konfiguracji")).toBeInTheDocument();
  });

  it("preserves timezone selection and diagnosis actions", async () => {
    await mount(); open("Strefa czasowa");
    expect(await screen.findByRole("button", { name: "Aktualna" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ustaw" }));
    await waitFor(() => expect(ntpManagerClient.setTimezone).toHaveBeenCalledWith("UTC"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Odśwież" })).toBeEnabled());
    open("Diagnostyka");
    fireEvent.click(screen.getByRole("button", { name: "Uruchom diagnostykę" }));
    expect(await screen.findByText("Usługa działa")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż szczegóły" }));
    expect(screen.getByRole("button", { name: "Ukryj szczegóły" })).toHaveAttribute("aria-expanded", "true");
  });

  it("does not synchronize when confirmation is declined", async () => {
    vi.mocked(confirmDialog).mockResolvedValue(false);
    await mount(); fireEvent.click(screen.getByRole("button", { name: "Synchronizuj teraz" }));
    await waitFor(() => expect(confirmDialog).toHaveBeenCalled());
    expect(ntpManagerClient.sync).not.toHaveBeenCalled();
  });
});

describe("NTP presentation", () => {
  it("maps raw backend values without confusing missing data and disabled mode", () => {
    expect(modeLabel()).toBe("Brak danych");
    expect(modeLabel("disabled")).toBe("Wyłączony");
    expect(backendLabel("none")).toBe("Brak usługi");
    expect(firewallLabel("unknown")).toBe("Niezweryfikowany");
    expect(formatTimestamp(Number.NaN)).toBe("Brak danych");
  });
  it("does not paint degraded or disabled synchronization as healthy", () => {
    expect(syncPresentation({ ...data, health: "degraded" }).tone).toBe("warning");
    expect(syncPresentation({ ...data, role: "disabled" }).title).toBe("Synchronizacja wyłączona");
    expect(syncPresentation({ ...data, synchronized: false }).title).toBe("Brak synchronizacji");
    expect(syncPresentation({ ...data, available: false }).title).toBe("Usługa NTP niedostępna");
  });
});
