import { Link, Plus, RefreshCw, Search, Settings, Trash2, Unlink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type DockerNetwork, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { CreateNetworkDialog } from "./CreateNetworkDialog";
import {
  DefaultBridgeNetworkDialog,
  NetworkContainerDialog,
  PruneNetworksDialog,
  RemoveNetworkDialog,
} from "./NetworkDialogs";
import { DockerTable, LoadState, errorMessage } from "./shared";

type Dialog =
  | { action: "create" | "prune" | "default-bridge" }
  | { action: "remove" | "connect" | "disconnect"; network: DockerNetwork };

function values(row: DockerNetwork, key: "subnets" | "gateways") {
  return Array.isArray(row[key]) ? row[key] : [];
}

function Tags({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="docker-empty-value">{empty}</span>;
  const visible = items.slice(0, 2);
  return (
    <span className="docker-network-tags" title={items.join("\n")}>
      {visible.map((item) => <code key={item}>{item}</code>)}
      {items.length > visible.length && <span>+{items.length - visible.length}</span>}
    </span>
  );
}

export function NetworksManager({
  permissions,
  refreshToken = 0,
  t,
  toast,
  onJob,
}: {
  permissions: string[];
  refreshToken?: number;
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [items, setItems] = useState<DockerNetwork[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.dockerNetworks(search)).items);
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [search, t]);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const protectedTitle = t("docker.systemNetworkProtected");
  return (
    <>
      <section>
        <div className="docker-section-toolbar">
          <label className="docker-search">
            <Search />
            <input
              aria-label={t("action.search")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <button onClick={() => void load()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
          {permissions.includes("docker.update_engine") && (
            <button onClick={() => setDialog({ action: "default-bridge" })}>
              <Settings />
              {t("docker.configureDefaultBridge")}
            </button>
          )}
          <button className="button-primary" onClick={() => setDialog({ action: "create" })}>
            <Plus />
            {t("docker.createNetwork")}
          </button>
          {permissions.includes("docker.prune") && (
            <button className="button-danger" onClick={() => setDialog({ action: "prune" })}>
              <Trash2 />
              {t("docker.pruneNetworks")}
            </button>
          )}
        </div>
        <LoadState loading={loading} error={error} retry={() => void load()} t={t}>
          <DockerTable
            items={items}
            empty={t("docker.noNetworks")}
            actionsLabel={t("docker.field.actions")}
            columns={[
              {
                key: "Name",
                label: t("docker.field.name"),
                render: (value, row) => (
                  <span className="docker-network-name">
                    <strong>{String(value || "")}</strong>
                    {Boolean(row.system) && <small title={protectedTitle}>{t("docker.systemNetwork")}</small>}
                  </span>
                ),
              },
              { key: "Driver", label: t("docker.field.driver") },
              { key: "Scope", label: t("docker.field.scope") },
              {
                key: "IPv6",
                label: t("docker.field.ipv6"),
                render: (value) => value ? t("common.yes") : t("common.no"),
              },
              {
                key: "subnets",
                label: t("docker.field.subnets"),
                render: (_value, row) => <Tags items={values(row as DockerNetwork, "subnets")} empty="—" />,
              },
              {
                key: "gateways",
                label: t("docker.field.gateways"),
                render: (_value, row) => <Tags items={values(row as DockerNetwork, "gateways")} empty="—" />,
              },
              {
                key: "container_count",
                label: t("docker.field.containers"),
                render: (value, row) => {
                  const containers = Array.isArray(row.containers) ? row.containers : [];
                  return <span title={containers.map((item) => item.name).filter(Boolean).join("\n")}>{String(value ?? 0)}</span>;
                },
              },
            ]}
            actions={(record) => {
              const network = record as DockerNetwork;
              const system = Boolean(network.system) || ["bridge", "host", "none"].includes(network.Name);
              return (
                <>
                  <button
                    title={system ? protectedTitle : t("docker.connectContainer")}
                    disabled={system}
                    onClick={() => setDialog({ action: "connect", network })}
                  >
                    <Link />
                  </button>
                  <button
                    title={system ? protectedTitle : t("docker.disconnectContainer")}
                    disabled={system || Number(network.container_count || 0) === 0}
                    onClick={() => setDialog({ action: "disconnect", network })}
                  >
                    <Unlink />
                  </button>
                  {permissions.includes("docker.high_risk") && (
                    <button
                      className="danger-icon"
                      title={system ? protectedTitle : t("action.delete")}
                      disabled={system}
                      onClick={() => setDialog({ action: "remove", network })}
                    >
                      <Trash2 />
                    </button>
                  )}
                </>
              );
            }}
          />
        </LoadState>
      </section>

      {dialog?.action === "create" && (
        <CreateNetworkDialog
          existingNames={items.map((item) => item.Name)}
          t={t}
          toast={toast}
          onClose={() => setDialog(null)}
          onJob={onJob}
        />
      )}
      {(dialog?.action === "connect" || dialog?.action === "disconnect") && (
        <NetworkContainerDialog
          action={dialog.action}
          network={dialog.network}
          t={t}
          toast={toast}
          onClose={() => setDialog(null)}
          onJob={onJob}
        />
      )}
      {dialog?.action === "remove" && (
        <RemoveNetworkDialog
          network={dialog.network}
          t={t}
          toast={toast}
          onClose={() => setDialog(null)}
          onJob={onJob}
        />
      )}
      {dialog?.action === "prune" && (
        <PruneNetworksDialog t={t} toast={toast} onClose={() => setDialog(null)} onJob={onJob} />
      )}
      {dialog?.action === "default-bridge" && (
        <DefaultBridgeNetworkDialog t={t} toast={toast} onClose={() => setDialog(null)} onJob={onJob} />
      )}
    </>
  );
}
