import type { NtpDiagnostics, NtpMode } from "./api/client";

export type NtpSection = "overview" | "sources" | "server" | "clients" | "timezone" | "diagnostics" | "history" | "config";

export function modeLabel(mode?: NtpMode): string {
  return mode ? { disabled: "Wyłączony", client: "Klient NTP", server: "Serwer NTP", client_server: "Klient + serwer" }[mode] : "Brak danych";
}

export function backendLabel(backend?: string): string {
  if (!backend || backend === "none") return "Brak usługi";
  return backend === "chrony" ? "Chrony" : backend;
}

export function serviceLabel(state?: string): string {
  return ({ active: "Uruchomiona", running: "Uruchomiona", inactive: "Zatrzymana", dead: "Zatrzymana", failed: "Błąd usługi", activating: "Uruchamianie", deactivating: "Zatrzymywanie", disabled: "Wyłączona", unavailable: "Niedostępna", unknown: "Nieznany" } as Record<string, string>)[state || ""] || state || "Brak danych";
}

export function firewallLabel(state?: string): string {
  return ({ open: "Otwarty", blocked: "Zablokowany", unknown: "Niezweryfikowany" } as Record<string, string>)[state || ""] || "Niezweryfikowany";
}

export function sourceStateLabel(state?: string): string {
  return ({ selected: "Synchronizacja", candidate: "Dostępny", outlier: "Nieużywany", unreachable: "Niedostępny", falseticker: "Błędny", jittery: "Niestabilny" } as Record<string, string>)[state || ""] || state || "Skonfigurowany";
}

export function formatTimestamp(timestamp?: number, language = "pl"): string {
  if (!timestamp || !Number.isFinite(timestamp)) return "Brak danych";
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return "Brak danych";
  try { return date.toLocaleString(language); }
  catch { return date.toLocaleString("pl"); }
}

export function syncPresentation(data: NtpDiagnostics): { title: string; detail: string; tone: "success" | "warning" | "neutral"; target: NtpSection; action: string } {
  if (!data.available || data.health === "unavailable") return {
    title: "Usługa NTP niedostępna", detail: "Sprawdź konfigurację usługi. Jeżeli nie jest zainstalowana, możesz zainstalować Chrony.", tone: "warning", target: "config", action: "Przejdź do konfiguracji",
  };
  if (data.role === "disabled") return {
    title: "Synchronizacja wyłączona", detail: "Wybierz tryb pracy, aby korzystać z klienta lub serwera czasu NTP.", tone: "neutral", target: "server", action: "Wybierz tryb pracy",
  };
  if (data.role === "server") return {
    title: "Serwer NTP aktywny", detail: "Host pracuje wyłącznie jako serwer czasu. Synchronizacja ze źródłem zewnętrznym nie jest wymagana w tym trybie.", tone: data.health === "degraded" ? "warning" : "success", target: "clients", action: "Zobacz klientów",
  };
  if (data.synchronized) return {
    title: "Czas zsynchronizowany", detail: data.health === "degraded" ? "Zegar jest zsynchronizowany, ale diagnostyka wykryła ostrzeżenia." : "Zegar systemowy korzysta z zewnętrznego źródła czasu.", tone: data.health === "degraded" ? "warning" : "success", target: "diagnostics", action: "Zobacz diagnostykę",
  };
  return {
    title: "Brak synchronizacji", detail: "Zegar nie potwierdził synchronizacji. Sprawdź dostępność źródeł i stan usługi.", tone: "warning", target: "sources", action: "Sprawdź źródła czasu",
  };
}
