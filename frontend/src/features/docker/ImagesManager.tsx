import {
  Download,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type DockerImage, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { DockerTable, LoadState, errorMessage } from "./shared";

export function ImagesManager({
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
  const [items, setItems] = useState<DockerImage[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<{
    action: "pull" | "remove" | "save";
    image?: string;
  } | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems((await api.dockerImages({ search, page_size: 200 })).items);
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setLoading(false);
    }
  }, [search, t]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    const image = dialog.image || values.image;
    try {
      onJob(
        (
          await api.dockerImageAction({
            action: dialog.action,
            image,
            platform: values.platform ? values.platform as "linux/amd64" | "linux/arm64" | "linux/arm/v7" : undefined,
            confirmation: image,
            force: values.force === "true",
            pam_password: values.pam_password || null,
          })
        ).job,
      );
      setDialog(null);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    }
  }
  async function importImage(file?: File) {
    if (!file) return;
    try {
      onJob((await api.importDockerImage(file)).job);
    } catch (reason) {
      toast(errorMessage(reason, t), "error", "admin");
    } finally {
      if (upload.current) upload.current.value = "";
    }
  }
  return (
    <>
      <section>
        <div className="docker-section-toolbar">
          <label className="docker-search">
            <Search />
            <span className="visually-hidden">{t("action.search")}</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("action.search")}
            />
          </label>
          <button onClick={() => void load()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
          {permissions.includes("docker.pull_image") && (
            <button
              className="button-primary"
              onClick={() => setDialog({ action: "pull" })}
            >
              <Download />
              {t("docker.pullImage")}
            </button>
          )}
          {permissions.includes("docker.restore_backup") && (
            <>
              <input
                ref={upload}
                className="visually-hidden"
                type="file"
                accept=".tar,.tar.gz,.tgz"
                onChange={(event) => void importImage(event.target.files?.[0])}
              />
              <button onClick={() => upload.current?.click()}>
                <Upload />
                {t("docker.loadImage")}
              </button>
            </>
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
            empty={t("docker.noImages")}
            columns={[
              { key: "Repository", label: t("docker.field.repository") },
              { key: "Tag", label: t("docker.field.tag") },
              { key: "Digest", label: t("docker.field.digest") },
              { key: "Size", label: t("docker.field.size") },
              { key: "CreatedSince", label: t("docker.field.created") },
              { key: "consumers", label: t("docker.field.consumers") },
            ]}
            actions={(row) => {
              const image = `${row.Repository}:${row.Tag}`;
              return (
                <>
                  <button
                    title={t("docker.saveImage")}
                    disabled={!permissions.includes("docker.export_backup")}
                    onClick={() => setDialog({ action: "save", image })}
                  >
                    <Save />
                  </button>
                  <button
                    title={t("action.delete")}
                    className="danger-icon"
                    disabled={!permissions.includes("docker.remove_image")}
                    onClick={() => setDialog({ action: "remove", image })}
                  >
                    <Trash2 />
                  </button>
                </>
              );
            }}
          />
        </LoadState>
      </section>
      {dialog && (
        <AdminActionDialog
          title={t(`docker.${dialog.action}Image`)}
          danger={dialog.action === "remove"}
          fields={[
            ...(!dialog.image
              ? [
                  {
                    name: "image",
                    label: t("docker.field.image"),
                    required: true,
                  },
                ]
              : []),
            ...(dialog.action === "pull"
              ? [{
                  name: "platform",
                  label: t("docker.field.platform"),
                  type: "select" as const,
                  value: "",
                  options: [
                    { value: "", label: t("docker.platformAutomatic") },
                    { value: "linux/amd64", label: "linux/amd64" },
                    { value: "linux/arm64", label: "linux/arm64" },
                    { value: "linux/arm/v7", label: "linux/arm/v7" },
                  ],
                }]
              : []),
            ...(dialog.action === "remove"
              ? [
                  {
                    name: "force",
                    label: t("docker.forceRemove"),
                    type: "select" as const,
                    value: "false",
                    options: [
                      { value: "false", label: t("common.no") },
                      { value: "true", label: t("common.yes") },
                    ],
                  },
                  {
                    name: "pam_password",
                    label: t("docker.currentPassword"),
                    type: "password" as const,
                  },
                ]
              : []),
          ]}
          t={t}
          onClose={() => setDialog(null)}
          onSubmit={submit}
        />
      )}
    </>
  );
}
