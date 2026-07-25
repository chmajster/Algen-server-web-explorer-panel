import { CircleAlert, Download, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type DockerRegistryCatalogImage, type ModuleJob } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { errorMessage } from "./shared";

export function RegistryImageDialog({
  image,
  canPull,
  t,
  toast,
  onClose,
  onJob,
}: {
  image: DockerRegistryCatalogImage;
  canPull: boolean;
  t: Translate;
  toast: ToastFn;
  onClose: () => void;
  onJob: (job: ModuleJob) => void;
}) {
  const [tags, setTags] = useState<string[]>([]);
  const [pullReference, setPullReference] = useState(image.pull_reference);
  const [filter, setFilter] = useState("");
  const [selectedTag, setSelectedTag] = useState("");
  const [platform, setPlatform] = useState("");
  const [loading, setLoading] = useState(true);
  const [pulling, setPulling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError("");
      try {
        const collected: string[] = [];
        let page = 1;
        let hasNext = true;
        while (hasNext && page <= 5) {
          const result = await api.dockerRegistryTags(image.registry_id, image.repository, page, 100);
          if (cancelled) return;
          setPullReference(result.pull_reference);
          for (const tag of result.tags) if (!collected.includes(tag)) collected.push(tag);
          hasNext = result.pagination.has_next;
          page += 1;
        }
        if (cancelled) return;
        setTags(collected);
        setSelectedTag(collected.includes("latest") ? "latest" : "");
      } catch (reason) {
        if (!cancelled) setError(registryError(reason, t));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [image.registry_id, image.repository, t]);

  const visibleTags = useMemo(() => {
    const normalized = filter.trim().toLocaleLowerCase();
    return normalized ? tags.filter((tag) => tag.toLocaleLowerCase().includes(normalized)) : tags;
  }, [filter, tags]);

  async function pull() {
    if (!selectedTag || !canPull) return;
    setPulling(true);
    try {
      const result = await api.dockerImageAction({
        action: "pull",
        image: `${pullReference}:${selectedTag}`,
        platform: platform ? platform as "linux/amd64" | "linux/arm64" | "linux/arm/v7" : undefined,
      });
      onJob(result.job);
      toast(t("docker.registry.pullStarted"), "ok", "admin");
      onClose();
    } catch (reason) {
      setError(errorMessage(reason, t));
    } finally {
      setPulling(false);
    }
  }

  return (
    <Modal
      title={t("docker.registry.imageDetails")}
      closeLabel={t("action.close")}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>{t("action.cancel")}</button>
          {canPull && (
            <button className="button-primary" type="button" disabled={loading || pulling || !selectedTag} onClick={() => void pull()}>
              <Download />
              {pulling ? t("status.loading") : t("docker.pullImage")}
            </button>
          )}
        </>
      }
    >
      <section className="registry-image-details">
        <header>
          <strong>{image.repository}</strong>
          <span>{image.description || t("docker.registry.noDescription")}</span>
        </header>
        <dl>
          <div><dt>{t("docker.registry.fullName")}</dt><dd><code>{pullReference}</code></dd></div>
          <div><dt>{t("docker.registry.source")}</dt><dd>{image.registry}</dd></div>
          <div><dt>{t("docker.field.provider")}</dt><dd>{image.provider}</dd></div>
        </dl>
        {!canPull && <p className="docker-notice warning"><CircleAlert />{t("docker.registry.noPullPermission")}</p>}
        <label className="docker-search registry-tag-filter">
          <Search />
          <span className="visually-hidden">{t("docker.registry.filterTags")}</span>
          <input
            aria-label={t("docker.registry.filterTags")}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={t("docker.registry.filterTags")}
          />
        </label>
        {loading ? (
          <div className="loading-state" role="status">{t("status.loading")}</div>
        ) : error ? (
          <p className="docker-notice error" role="alert"><CircleAlert />{error}</p>
        ) : tags.length === 0 ? (
          <div className="empty-state"><strong>{t("docker.registry.noTags")}</strong></div>
        ) : (
          <label className="field-label">
            {t("docker.registry.availableTags")}
            <select aria-label={t("docker.registry.availableTags")} value={selectedTag} onChange={(event) => setSelectedTag(event.target.value)}>
              <option value="">{t("docker.registry.chooseTag")}</option>
              {visibleTags.map((tag) => <option value={tag} key={tag}>{tag}</option>)}
            </select>
            {visibleTags.length === 0 && <small>{t("docker.registry.noMatchingTags")}</small>}
          </label>
        )}
        <label className="field-label">
          {t("docker.field.platform")}
          <select aria-label={t("docker.field.platform")} value={platform} onChange={(event) => setPlatform(event.target.value)}>
            <option value="">{t("docker.platformAutomatic")}</option>
            <option value="linux/amd64">linux/amd64</option>
            <option value="linux/arm64">linux/arm64</option>
            <option value="linux/arm/v7">linux/arm/v7</option>
          </select>
        </label>
      </section>
    </Modal>
  );
}

function registryError(reason: unknown, t: Translate): string {
  if (reason instanceof ApiError) {
    if (reason.code === "REGISTRY_CATALOG_UNSUPPORTED") return t("docker.registry.catalogUnsupported");
    if (reason.code === "REGISTRY_TIMEOUT") return t("docker.registry.timeout");
    if (reason.code === "REGISTRY_AUTH_FAILED") return t("docker.registry.authFailed");
  }
  return errorMessage(reason, t);
}
