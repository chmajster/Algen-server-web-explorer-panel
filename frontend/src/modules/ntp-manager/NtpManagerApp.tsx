import { Clock, Plus, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { ToastFn } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import { ntpManagerClient, type NtpSource, type NtpStatus } from "./api/client";
import "../infrastructure-managers.css";

type Props = {
  permissions: string[];
  language: string;
  toast: ToastFn;
};

export function NtpManagerApp({ permissions, toast }: Props) {
  const [status, setStatus] = useState<NtpStatus | null>(null);
  const [sources, setSources] = useState<NtpSource[]>([]);
  const [server, setServer] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStatus, nextSources] = await Promise.all([
        ntpManagerClient.dashboard(),
        ntpManagerClient.sources(),
      ]);
      setStatus(nextStatus);
      setSources(nextSources.items);
    } catch (error) {
      toast(error instanceof Error ? error.message : "NTP error", "error", "admin", "ntp-manager");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runAction(action: () => Promise<unknown>) {
    try {
      await action();
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : "NTP action failed", "error", "admin", "ntp-manager");
    }
  }

  async function addServer() {
    const value = server.trim();
    if (!value) return;
    await runAction(() => ntpManagerClient.add(value));
    setServer("");
  }

  async function testServer(value: string) {
    try {
      const result = await ntpManagerClient.test(value);
      toast(
        `${value}: ${result.ok ? "OK" : "failed"}`,
        result.ok ? "success" : "error",
        "admin",
        "ntp-manager",
      );
    } catch (error) {
      toast(error instanceof Error ? error.message : "NTP test failed", "error", "admin", "ntp-manager");
    }
  }

  return (
    <div className="infra-manager-app">
      <header className="infra-manager-header">
        <div className="infra-manager-title">
          <Clock />
          <div>
            <h2>NTP Manager</h2>
            <p>Time synchronization, sources, offset and service state.</p>
          </div>
        </div>
        <div className="infra-manager-actions">
          {permissions.includes("ntp.resync") && (
            <button type="button" onClick={() => void runAction(ntpManagerClient.resync)}>
              <RotateCcw />
              Resync
            </button>
          )}
          {permissions.includes("ntp.manage") && (
            <button
              type="button"
              onClick={async () => {
                if (await confirmDialog("Restart NTP service?", (key) => key)) {
                  void runAction(() => ntpManagerClient.service("restart"));
                }
              }}
            >
              Restart
            </button>
          )}
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={loading ? "spin" : ""} />
            Refresh
          </button>
        </div>
      </header>

      <div className="infra-stat-grid">
        <div className="infra-stat">
          <strong>{status?.synchronized ? "Synchronized" : "Not synchronized"}</strong>
          <small>{status?.backend || "none"}</small>
        </div>
        <div className="infra-stat">
          <strong>{status?.stratum ?? "—"}</strong>
          <small>Stratum</small>
        </div>
        <div className="infra-stat">
          <strong>{status?.offset || "—"}</strong>
          <small>Offset</small>
        </div>
        <div className="infra-stat">
          <strong>{status?.timezone || "—"}</strong>
          <small>Timezone</small>
        </div>
        <div className="infra-stat">
          <strong>{status?.service_state || "—"}</strong>
          <small>{status?.service || "Service"}</small>
        </div>
      </div>

      {permissions.includes("ntp.manage") && (
        <div className="infra-manager-toolbar">
          <input
            aria-label="NTP server"
            placeholder="time.example.org"
            value={server}
            onChange={(event) => setServer(event.target.value)}
          />
          <button type="button" onClick={() => void addServer()} disabled={!server.trim()}>
            <Plus />
            Add server
          </button>
        </div>
      )}

      <div className="infra-table-wrap">
        <table className="infra-table">
          <thead>
            <tr>
              <th>Server</th>
              <th>State</th>
              <th>Selected</th>
              <th>Stratum</th>
              <th>Reach</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.server}>
                <td>{source.server}</td>
                <td>{source.state || "configured"}</td>
                <td>{source.selected ? "yes" : "no"}</td>
                <td>{source.stratum ?? "—"}</td>
                <td>{source.reach ?? "—"}</td>
                <td>
                  <div className="infra-row-actions">
                    <button type="button" onClick={() => void testServer(source.server)}>
                      Test
                    </button>
                    {permissions.includes("ntp.manage") && (
                      <button
                        type="button"
                        onClick={async () => {
                          if (await confirmDialog(`Remove ${source.server}?`, (key) => key)) {
                            void runAction(() => ntpManagerClient.remove(source.server));
                          }
                        }}
                      >
                        <Trash2 />
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
