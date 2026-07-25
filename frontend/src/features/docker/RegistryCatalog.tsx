import { Download, Info, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type DockerRegistryCatalogImage,
  type DockerRegistryCatalogResult,
  type DockerRegistrySource,
  type ModuleJob,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { DockerTable, errorMessage } from "./shared";
import { RegistryImageDialog } from "./RegistryImageDialog";

export function RegistryCatalog({
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
  const [sources, setSources] = useState<DockerRegistrySource[]>([]);
  const [registryId, setRegistryId] = useState("docker-hub-public");
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [official, setOfficial] = useState<"all" | "official" | "unofficial">("all");
  const [sort, setSort] = useState<"relevance" | "name" | "stars">("relevance");
  const [pageSize, setPageSize] = useState(25);
  const [result, setResult] = useState<DockerRegistryCatalogResult | null>(null);
  const [selected, setSelected] = useState<DockerRegistryCatalogImage | null>(null);
  const [loadingSources, setLoadingSources] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState("");
  const request = useRef(0);
  const canPull = permissions.includes("docker.pull_image");

  const loadSources = useCallback(async () => {
    setLoadingSources(true);
    try {
      const next = await api.dockerRegistrySources();
      setSources(next);
      setRegistryId((current) => next.some((source) => source.id === current) ? current : next[0]?.id || "");
      setError("");
    } catch (reason) {
      setError(registryError(reason, t));
    } finally {
      setLoadingSources(false);
    }
  }, [t]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  async function searchImages(searchQuery = query, page = 1) {
    const normalized = searchQuery.trim();
    if (normalized.length < 2) {
      setValidation(t("docker.registrySearchTooShort"));
      return;
    }
    if (!registryId) {
      setError(t("docker.registry.noSources"));
      return;
    }
    const sequence = ++request.current;
    setValidation("");
    setError("");
    setLoading(true);
    try {
      const next = await api.dockerRegistryCatalog({
        registry_id: registryId,
        query: normalized,
        page,
        page_size: pageSize,
        official,
        sort,
        direction: sort === "name" ? "asc" : "desc",
      });
      if (sequence !== request.current) return;
      setResult(next);
      setActiveQuery(normalized);
    } catch (reason) {
      if (sequence === request.current) {
        setResult(null);
        setError(registryError(reason, t));
      }
    } finally {
      if (sequence === request.current) setLoading(false);
    }
  }

  const items = result?.items || [];
  return (
    <>
      <section className="registry-catalog">
        <form className="registry-catalog-toolbar" onSubmit={(event) => { event.preventDefault(); void searchImages(); }}>
          <label className="docker-search">
            <Search />
            <span className="visually-hidden">{t("docker.registry.searchImages")}</span>
            <input
              aria-label={t("docker.registry.searchImages")}
              value={query}
              onChange={(event) => { setQuery(event.target.value); setValidation(""); }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void searchImages();
                }
              }}
              placeholder={t("docker.registry.searchImages")}
            />
          </label>
          <label>
            <span>{t("docker.registry.chooseRegistry")}</span>
            <select aria-label={t("docker.registry.chooseRegistry")} disabled={loadingSources} value={registryId} onChange={(event) => setRegistryId(event.target.value)}>
              {sources.map((source) => <option value={source.id} key={source.id}>{source.name}</option>)}
            </select>
          </label>
          <button className="button-primary" type="submit" disabled={loading || loadingSources}>
            <Search />
            {t("action.search")}
          </button>
          <button type="button" disabled={loading} onClick={() => activeQuery ? void searchImages(activeQuery, result?.pagination.page || 1) : void loadSources()}>
            <RefreshCw />
            {t("action.refresh")}
          </button>
          <label>
            <span>{t("docker.registry.imageFilter")}</span>
            <select aria-label={t("docker.registry.imageFilter")} value={official} onChange={(event) => setOfficial(event.target.value as typeof official)}>
              <option value="all">{t("docker.registry.filterAll")}</option>
              <option value="official">{t("docker.registry.filterOfficial")}</option>
              <option value="unofficial">{t("docker.registry.filterUnofficial")}</option>
            </select>
          </label>
          <label>
            <span>{t("docker.registry.sort")}</span>
            <select aria-label={t("docker.registry.sort")} value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
              <option value="relevance">{t("docker.registry.sortRelevance")}</option>
              <option value="name">{t("docker.registry.sortName")}</option>
              <option value="stars">{t("docker.registry.sortStars")}</option>
            </select>
          </label>
          <label>
            <span>{t("docker.registry.pageSize")}</span>
            <select aria-label={t("docker.registry.pageSize")} value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
        </form>
        {validation && <p className="docker-notice warning" role="alert">{validation}</p>}
        {error && <p className="docker-notice error" role="alert">{error}</p>}
        {loading ? (
          <div className="loading-state" role="status">{t("status.loading")}</div>
        ) : !result ? (
          <div className="registry-catalog-intro"><Search /><strong>{t("docker.registry.catalogIntroTitle")}</strong><span>{t("docker.registry.catalogIntro")}</span></div>
        ) : (
          <>
            <DockerTable
              items={items}
              empty={t("docker.registry.noResults")}
              actionsLabel={t("managed.actions")}
              onRowClick={(row) => setSelected(row as DockerRegistryCatalogImage)}
              columns={[
                { key: "registry", label: t("docker.registry.source") },
                { key: "repository", label: t("docker.field.repository") },
                { key: "description", label: t("docker.field.description") },
                { key: "provider", label: t("docker.field.provider") },
                { key: "stars", label: t("docker.field.stars") },
                { key: "official", label: t("docker.field.official"), render: (value) => <BooleanBadge value={Boolean(value)} t={t} /> },
                { key: "automated", label: t("docker.field.automated"), render: (value) => value === null ? <span className="docker-empty-value">—</span> : <BooleanBadge value={Boolean(value)} t={t} /> },
              ]}
              actions={(row) => {
                const image = row as DockerRegistryCatalogImage;
                return (
                  <>
                    <button title={t("docker.registry.imageDetails")} aria-label={t("docker.registry.imageDetails")} onClick={() => setSelected(image)}><Info /></button>
                    {canPull && <button title={t("docker.pullImage")} aria-label={t("docker.pullImage")} onClick={() => setSelected(image)}><Download /></button>}
                  </>
                );
              }}
            />
            <div className="docker-pagination">
              <button type="button" disabled={result.pagination.page <= 1 || loading} onClick={() => void searchImages(activeQuery, result.pagination.page - 1)}>{t("action.previous")}</button>
              <span>{t("docker.registry.page")} {result.pagination.page} / {Math.max(result.pagination.pages, 1)}</span>
              <button type="button" disabled={!result.pagination.has_next || loading} onClick={() => void searchImages(activeQuery, result.pagination.page + 1)}>{t("action.next")}</button>
            </div>
          </>
        )}
      </section>
      {selected && <RegistryImageDialog image={selected} canPull={canPull} t={t} toast={toast} onClose={() => setSelected(null)} onJob={onJob} />}
    </>
  );
}

function BooleanBadge({ value, t }: { value: boolean; t: Translate }) {
  return <span className={`registry-boolean ${value ? "yes" : "no"}`}>{t(value ? "common.yes" : "common.no")}</span>;
}

function registryError(reason: unknown, t: Translate): string {
  if (reason instanceof ApiError) {
    if (reason.code === "REGISTRY_CATALOG_UNSUPPORTED") return t("docker.registry.catalogUnsupported");
    if (reason.code === "REGISTRY_TIMEOUT") return t("docker.registry.timeout");
    if (reason.code === "REGISTRY_AUTH_FAILED") return t("docker.registry.authFailed");
    if (reason.code === "UNSAFE_REGISTRY_URL") return t("docker.registry.unsafeAddress");
  }
  return errorMessage(reason, t);
}
