import { Link, Plus, RefreshCw, Search, Trash2, Unlink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

export function NetworksManager({
  permissions,
  t,
  toast,
  onJob,
}: {
  permissions: string[];
  t: Translate;
  toast: ToastFn;
  onJob: (job: ModuleJob) => void;
}) {
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    action: "create" | "remove" | "connect" | "disconnect" | "prune";
    target?: string;
  } | null>(null);
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
  }, [load]);
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    try {
      const result =
        dialog.action === "create"
          ? await api.createDockerNetwork({
              name: values.name,
              driver: "bridge",
              subnet: values.subnet || null,
              gateway: values.gateway || null,
              internal: false,
              ipv6: false,
              labels: {},
            })
          : await api.dockerNetworkAction(dialog.target || "", {
              action: dialog.action,
              container: values.container || null,
              confirmation: dialog.action === "prune" ? "networks" : dialog.target || "",
              pam_password: values.pam_password || null,
            });
      onJob(result.job);
      setDialog(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
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
          <button
            className="button-primary"
            onClick={() => setDialog({ action: "create" })}
          >
            <Plus />
            {t("docker.createNetwork")}
          </button>
          {permissions.includes("docker.prune") && (
            <button className="button-danger" onClick={() => setDialog({ action: "prune", target: "networks" })}>
              <Trash2 />{t("docker.pruneNetworks")}
            </button>
          )}
        </div>
        <LoadState
          loading={loading}
          error={error}
          retry={() => void load()}
          t={t}
        >
          <DockerTable
            items={items}
            empty={t("docker.noNetworks")}
            columns={[
              { key: "Name", label: t("docker.field.name") },
              { key: "Driver", label: t("docker.field.driver") },
              { key: "Scope", label: t("docker.field.scope") },
              { key: "IPv6", label: t("docker.field.ipv6") },
            ]}
            actions={(row) => {
              const target = String(row.Name || "");
              const system = ["bridge", "host", "none"].includes(target);
              return (
                <>
                  <button
                    title={t("docker.connectContainer")}
                    disabled={system}
                    onClick={() => setDialog({ action: "connect", target })}
                  >
                    <Link />
                  </button>
                  <button
                    title={t("docker.disconnectContainer")}
                    disabled={system}
                    onClick={() => setDialog({ action: "disconnect", target })}
                  >
                    <Unlink />
                  </button>
                  {permissions.includes("docker.high_risk") && (
                    <button
                      className="danger-icon"
                      title={t("action.delete")}
                      disabled={system}
                      onClick={() => setDialog({ action: "remove", target })}
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
      {dialog && (
        <AdminActionDialog
          title={t(`docker.networkAction.${dialog.action}`)}
          danger={dialog.action === "remove" || dialog.action === "prune"}
          fields={
            dialog.action === "create"
              ? [
                  {
                    name: "name",
                    label: t("docker.field.name"),
                    required: true,
                  },
                  { name: "subnet", label: t("docker.field.subnet") },
                  { name: "gateway", label: t("docker.field.gateway") },
                ]
              : dialog.action === "connect" || dialog.action === "disconnect"
                ? [
                    {
                      name: "container",
                      label: t("docker.field.container"),
                      required: true,
                    },
                  ]
                : [
                    {
                      name: "pam_password",
                      label: t("docker.currentPassword"),
                      type: "password",
                      required: true,
                    },
                  ]
          }
          t={t}
          onClose={() => setDialog(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
