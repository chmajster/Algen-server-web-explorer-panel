import { useEffect } from "react";
import type { SettingsMe } from "../../api";
import { request } from "../../core/api/transport";
import { servicesClient } from "../../modules/services/api/client";
import { WebNAS } from "./WebNASShell";
import type { SearchResult } from "./managers";

type ContainerSearchRow = { Id?: string; ID?: string; Names?: string | string[]; Name?: string; State?: string; Status?: string };
type ContainerPage = { items?: ContainerSearchRow[] } | ContainerSearchRow[];

function containerName(item: ContainerSearchRow): string {
  if (typeof item.Name === "string" && item.Name.trim()) return item.Name.trim();
  if (typeof item.Names === "string" && item.Names.trim()) return item.Names.trim().replace(/^\//, "");
  if (Array.isArray(item.Names) && item.Names.length) return String(item.Names[0]).replace(/^\//, "");
  return item.Id || item.ID || "container";
}

export function SystemSearchProviders({ profile }: { profile: SettingsMe }) {
  useEffect(() => {
    const disposers: Array<() => void> = [];

    disposers.push(WebNAS.search.register("settings", (query) => {
      const sections = [
        ["personalization", "Personalizacja", ["pulpit", "tapeta", "taskbar", "start", "motyw"]],
        ["account", "Profil i konto", ["profil", "konto", "użytkownik"]],
        ["notifications", "Powiadomienia", ["powiadomienia", "toast", "alert"]],
        ["accessibility", "Dostępność", ["dostępność", "kontrast", "czcionka"]],
      ] as const;
      return sections.map(([section, title, keywords]) => ({
        id: `setting:${section}`,
        title,
        subtitle: "Ustawienia WebNAS",
        category: "setting" as const,
        keywords: [...keywords, query],
        run: () => WebNAS.window.open("settings", { initialPath: section }),
      }));
    }));

    disposers.push(WebNAS.search.register("admin-actions", () => {
      const values: SearchResult[] = [
        {
          id: "action:restart-webnas",
          title: "Restart WebNAS",
          subtitle: "Uruchom ponownie aplikację WebNAS",
          category: "action",
          keywords: ["restart", "webnas", "aplikacja"],
          permitted: () => profile.permissions.includes("system.restart"),
          run: () => WebNAS.session.restartWebNAS(),
        },
        {
          id: "action:restart-host",
          title: "Restart hosta",
          subtitle: "Uruchom ponownie system operacyjny",
          category: "action",
          keywords: ["restart", "reboot", "host", "serwer"],
          permitted: () => profile.permissions.includes("system.restart"),
          run: () => WebNAS.session.restartHost(),
        },
        {
          id: "action:shutdown-host",
          title: "Wyłącz hosta",
          subtitle: "Wyłącz system operacyjny",
          category: "action",
          keywords: ["shutdown", "poweroff", "host", "serwer"],
          permitted: () => profile.permissions.includes("system.shutdown"),
          run: () => WebNAS.session.shutdownHost(),
        },
      ];
      return values;
    }));

    if (profile.is_admin) {
      disposers.push(WebNAS.search.register("services", async (query) => {
        if (query.length < 2) return [];
        try {
          const services = await servicesClient.systemdServices();
          return services.slice(0, 500).flatMap((service): SearchResult[] => {
            const name = service.name;
            const base: SearchResult = {
              id: `service:${name}`,
              title: `${name} service`,
              subtitle: `${service.status}${service.sub_state ? ` · ${service.sub_state}` : ""}`,
              category: "service",
              keywords: [name, service.status, service.sub_state || "", "systemd", "service"],
              run: () => WebNAS.window.open("services"),
            };
            const actions: SearchResult[] = [
              {
                id: `service:${name}:logs`, title: `${name} — Otwórz logi`, subtitle: "Systemd", category: "action", keywords: [name, "logs", "logi"],
                run: () => WebNAS.window.open("services"),
              },
              ...(["start", "restart", "stop"] as const).map((action): SearchResult => ({
                id: `service:${name}:${action}`,
                title: `${name} — ${action === "start" ? "Start" : action === "stop" ? "Stop" : "Restart"}`,
                subtitle: "Akcja administracyjna systemd",
                category: "action",
                keywords: [name, action, "systemd"],
                run: async () => { await servicesClient.systemdServiceAction(name, action); },
              })),
            ];
            return [base, ...actions];
          });
        } catch { return []; }
      }));
    }

    if (profile.permissions.includes("modules.view") || profile.is_admin) {
      disposers.push(WebNAS.search.register("containers", async (query) => {
        if (query.length < 2) return [];
        try {
          const response = await request<ContainerPage>(`/api/modules/docker/containers?search=${encodeURIComponent(query)}&page_size=100`);
          const items = Array.isArray(response) ? response : response.items || [];
          return items.map((item): SearchResult => {
            const name = containerName(item);
            return {
              id: `container:${item.Id || item.ID || name}`,
              title: name,
              subtitle: `Kontener Docker${item.State || item.Status ? ` · ${item.State || item.Status}` : ""}`,
              category: "container",
              keywords: [name, item.Id || item.ID || "", item.State || "", item.Status || "", "docker", "container"],
              run: () => WebNAS.window.open("containers"),
            };
          });
        } catch { return []; }
      }));
    }

    return () => { for (const dispose of disposers) dispose(); };
  }, [profile.is_admin, profile.permissions]);

  return null;
}
