import {
  AlertCircle, Archive, BookMarked, Box, ChevronRight, CirclePause, CirclePlay, Clock3,
  Copy, Download, FileText, Filter, FolderTree, PanelLeftClose, PanelLeftOpen, RefreshCw, Save,
  Search, ServerCog, Settings2, ShieldAlert, Terminal, Trash2, WrapText, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, type LogBoot, type LogContainer, type LogEntry, type LogQuery, type LogSavedView,
  type LogService, type LogSourceGroup, type LogSourcesResponse,
} from "../../api";
import type { ToastFn, Translate } from "../../app/types";

type ViewMode = "compact" | "table";
type RangeValue = "5m" | "15m" | "1h" | "6h" | "24h" | "7d" | "custom" | "all";
type Filters = {
  priority: number[];
  unit: string;
  pid: string;
  uid: string;
  identifier: string;
  transport: string;
  hostname: string;
  device: string;
  username: string;
  group: string;
  boot_id: string;
  container_id: string;
  since: string;
  until: string;
  regex: boolean;
  case_sensitive: boolean;
  negate: boolean;
  message_only: boolean;
};

const emptyFilters: Filters = {
  priority: [], unit: "", pid: "", uid: "", identifier: "", transport: "", hostname: "", device: "", username: "", group: "", boot_id: "",
  container_id: "", since: "", until: "", regex: false, case_sensitive: false, negate: false, message_only: false,
};
const severityNames = ["emergency", "alert", "critical", "error", "warning", "notice", "info", "debug"];
const sourceIcons: Record<string, React.ReactNode> = {
  journal: <Terminal />, kernel: <ShieldAlert />, services: <ServerCog />, files: <FileText />,
  webnas: <Archive />, packages: <Archive />, containers: <Box />,
};

export function LogsApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [sources, setSources] = useState<LogSourcesResponse | null>(null);
  const [services, setServices] = useState<LogService[]>([]);
  const [boots, setBoots] = useState<LogBoot[]>([]);
  const [containers, setContainers] = useState<LogContainer[]>([]);
  const [savedViews, setSavedViews] = useState<LogSavedView[]>([]);
  const [source, setSource] = useState(permissions.includes("logs.view_system") ? "journal" : "activity-own");
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("webnas.log-search-history") || "[]") as string[]; } catch { return []; }
  });
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [range, setRange] = useState<RangeValue>("1h");
  const [rangeAnchor, setRangeAnchor] = useState(() => Date.now() / 1000);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("compact");
  const [wrap, setWrap] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [live, setLive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [pending, setPending] = useState<LogEntry[]>([]);
  const [scrollTop, setScrollTop] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);
  const autoScrollRef = useRef(true);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectRef = useRef<number | null>(null);

  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => { autoScrollRef.current = autoScroll; }, [autoScroll]);
  useEffect(() => {
    let active = true;
    void Promise.allSettled([api.logSources(), api.logServices(), api.logBoots(), api.logContainers(), api.logSavedViews()]).then((results) => {
      if (!active) return;
      if (results[0].status === "fulfilled") setSources(results[0].value);
      else setError(results[0].reason instanceof Error ? results[0].reason.message : t("error.generic"));
      if (results[1].status === "fulfilled") setServices(results[1].value.items);
      if (results[2].status === "fulfilled") setBoots(results[2].value.items);
      if (results[3].status === "fulfilled") setContainers(results[3].value.items);
      if (results[4].status === "fulfilled") setSavedViews(results[4].value.items);
    });
    return () => { active = false; };
  }, [t]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "f") {
        event.preventDefault(); searchRef.current?.focus(); searchRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(queryDraft.trim()), 400);
    return () => window.clearTimeout(timer);
  }, [queryDraft]);
  useEffect(() => { setRangeAnchor(Date.now() / 1000); }, [range]);

  const effectiveTimes = useMemo(() => {
    if (range === "custom") return { since: filters.since ? new Date(filters.since).getTime() / 1000 : null, until: filters.until ? new Date(filters.until).getTime() / 1000 : null };
    if (range === "all") return { since: null, until: null };
    const seconds = { "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800 }[range];
    return { since: rangeAnchor - seconds, until: null };
  }, [filters.since, filters.until, range, rangeAnchor]);
  const requestQuery = useMemo<LogQuery>(() => ({
    source, query, regex: filters.regex, case_sensitive: filters.case_sensitive, negate: filters.negate,
    message_only: filters.message_only, priority: filters.priority, unit: filters.unit,
    pid: filters.pid ? Number(filters.pid) : null, uid: filters.uid ? Number(filters.uid) : null,
    identifier: filters.identifier, transport: filters.transport, hostname: filters.hostname, device: filters.device,
    username: filters.username, group: filters.group, boot_id: filters.boot_id,
    container_id: filters.container_id, since: effectiveTimes.since, until: effectiveTimes.until, limit: 300,
  }), [effectiveTimes, filters, query, source]);
  const requestKey = useMemo(() => JSON.stringify(requestQuery), [requestQuery]);

  const load = useCallback(async (append = false, signal?: AbortSignal) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    if (!append) setError("");
    try {
      const result = await api.logEntries({ ...requestQuery, cursor: append ? cursor || "" : "", direction: "older" }, signal);
      setEntries((current) => append ? [...current, ...result.items].slice(0, 2000) : result.items);
      setCursor(result.next_cursor);
      if (!append) setSelected(null);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      if (append) setLoadingMore(false);
      else setLoading(false);
    }
  }, [cursor, requestQuery, t]);

  useEffect(() => {
    const controller = new AbortController();
    void load(false, controller.signal);
    return () => controller.abort();
    // requestKey represents the complete validated backend query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const streamUrl = useMemo(() => {
    const params = new URLSearchParams({ source, query });
    if (filters.regex) params.set("regex", "true");
    if (filters.case_sensitive) params.set("case_sensitive", "true");
    if (filters.negate) params.set("negate", "true");
    if (filters.message_only) params.set("message_only", "true");
    filters.priority.forEach((value) => params.append("priority", String(value)));
    if (filters.unit) params.set("unit", filters.unit);
    if (filters.pid) params.set("pid", filters.pid);
    if (filters.uid) params.set("uid", filters.uid);
    if (filters.identifier) params.set("identifier", filters.identifier);
    if (filters.transport) params.set("transport", filters.transport);
    if (filters.hostname) params.set("hostname", filters.hostname);
    if (filters.device) params.set("device", filters.device);
    if (filters.username) params.set("username", filters.username);
    if (filters.group) params.set("group", filters.group);
    if (filters.boot_id) params.set("boot_id", filters.boot_id);
    if (filters.container_id) params.set("container_id", filters.container_id);
    return `/api/logs/stream?${params}`;
  }, [filters, query, source]);

  useEffect(() => {
    if (!live || typeof EventSource === "undefined") return;
    let disposed = false;
    let retry = 1000;
    const connect = () => {
      if (disposed) return;
      const stream = new EventSource(streamUrl, { withCredentials: true });
      eventSourceRef.current = stream;
      stream.onopen = () => { retry = 1000; setError(""); };
      stream.onmessage = (event) => {
        try {
          const entry = JSON.parse(event.data) as LogEntry;
          if (pausedRef.current) setPending((current) => [...current, entry].slice(-1000));
          else {
            setEntries((current) => [entry, ...current.filter((item) => item.id !== entry.id)].slice(0, 2000));
            if (autoScrollRef.current && listRef.current) listRef.current.scrollTop = 0;
          }
        } catch { /* malformed source records are isolated */ }
      };
      stream.addEventListener("source-error", () => setError(t("logs.streamUnavailable")));
      stream.onerror = () => {
        stream.close();
        if (!disposed) {
          reconnectRef.current = window.setTimeout(connect, retry);
          retry = Math.min(retry * 2, 30000);
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      eventSourceRef.current?.close();
      if (reconnectRef.current) window.clearTimeout(reconnectRef.current);
    };
  }, [live, streamUrl, t]);

  function resume() {
    setPaused(false);
    setEntries((current) => [...[...pending].reverse(), ...current].slice(0, 2000));
    setPending([]);
    if (autoScroll && listRef.current) listRef.current.scrollTop = 0;
  }
  function rememberSearch() {
    if (!query) return;
    const next = [query, ...history.filter((item) => item !== query)].slice(0, 12);
    setHistory(next); localStorage.setItem("webnas.log-search-history", JSON.stringify(next));
  }
  function clearFilters() { setFilters(emptyFilters); setRange("1h"); }
  function onlyErrors() { setFilters((current) => ({ ...current, priority: [0, 1, 2, 3] })); }
  function currentBoot() { setSource("current-boot"); setFilters((current) => ({ ...current, boot_id: "" })); }
  function chooseSource(next: string) {
    setSource(next);
    if (next.startsWith("service:")) setFilters((current) => ({ ...current, unit: next.slice(8) }));
    if (next.startsWith("container:")) setFilters((current) => ({ ...current, container_id: next.slice(10) }));
  }
  function applySaved(view: LogSavedView) {
    setSource(view.source); setQueryDraft(view.query); setViewMode(view.view_mode);
    setFilters({ ...emptyFilters, ...view.filters, priority: Array.isArray(view.filters.priority) ? view.filters.priority as number[] : [] } as Filters);
  }
  async function saveView() {
    const name = window.prompt(t("logs.savedViewName"));
    if (!name?.trim()) return;
    try {
      const item = await api.createLogSavedView({ name: name.trim(), source, query, filters: filters as unknown as Record<string, string | number | boolean | number[]>, columns: ["timestamp", "severity", "source", "unit", "pid", "hostname", "message"], sort: "newest", view_mode: viewMode });
      setSavedViews((current) => [item, ...current]); toast(t("logs.savedViewCreated"), "ok");
    } catch (reason) { toast(reason instanceof Error ? reason.message : t("error.generic"), "error"); }
  }
  async function removeView(view: LogSavedView) {
    try { await api.deleteLogSavedView(view.id); setSavedViews((current) => current.filter((item) => item.id !== view.id)); }
    catch (reason) { toast(reason instanceof Error ? reason.message : t("error.generic"), "error"); }
  }
  async function exportView(format: "txt" | "json" | "jsonl" | "csv") {
    try {
      const result = await api.exportLogs({ ...requestQuery, format, limit: 5000 });
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a"); link.href = url; link.download = result.filename; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (result.truncated) toast(t("logs.exportTruncated"), "ok");
    } catch (reason) { toast(reason instanceof Error ? reason.message : t("error.generic"), "error"); }
  }

  const activeFilters = Object.entries(filters).filter(([key, value]) => key !== "priority" ? Boolean(value) : (value as number[]).length > 0).length + (range !== "all" ? 1 : 0);
  const rowHeight = viewMode === "compact" ? 42 : 58;
  const viewportHeight = 560;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 8);
  const end = Math.min(entries.length, start + Math.ceil(viewportHeight / rowHeight) + 16);
  const visible = entries.slice(start, end);

  return <section className={`logs-app ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${selected ? "details-open" : ""}`}>
    <aside className="logs-sidebar">
      <header><strong><FolderTree />{t("logs.sources")}</strong><button type="button" aria-label={t("logs.collapseSources")} onClick={() => setSidebarCollapsed(true)}><PanelLeftClose /></button></header>
      <SourceTree groups={sources?.groups || []} services={services} containers={containers} selected={source} t={t} onChoose={chooseSource} />
      <section className="logs-saved"><header><strong><BookMarked />{t("logs.savedViews")}</strong><button type="button" title={t("logs.saveView")} onClick={() => void saveView()}><Save /></button></header>{savedViews.map((view) => <div key={view.id}><button className={source === view.source && query === view.query ? "active" : ""} onClick={() => applySaved(view)}>{view.name}</button>{!view.builtin && <button aria-label={`${t("action.delete")}: ${view.name}`} onClick={() => void removeView(view)}><Trash2 /></button>}</div>)}</section>
    </aside>

    <main className="logs-main">
      <header className="logs-toolbar">
        {sidebarCollapsed && <button type="button" aria-label={t("logs.expandSources")} onClick={() => setSidebarCollapsed(false)}><PanelLeftOpen /></button>}
        <label className="logs-search"><Search /><input ref={searchRef} value={queryDraft} list="logs-search-history" aria-label={t("logs.search")} placeholder={t("logs.searchPlaceholder")} onChange={(event) => setQueryDraft(event.target.value)} onBlur={rememberSearch} /><datalist id="logs-search-history">{history.map((item) => <option key={item}>{item}</option>)}</datalist>{queryDraft ? <button type="button" aria-label={t("action.clear")} onClick={() => setQueryDraft("")}><X /></button> : history.length > 0 && <button type="button" title={t("logs.clearHistory")} aria-label={t("logs.clearHistory")} onClick={() => { setHistory([]); localStorage.removeItem("webnas.log-search-history"); }}><Trash2 /></button>}</label>
        <select aria-label={t("logs.timeRange")} value={range} onChange={(event) => setRange(event.target.value as RangeValue)}>{["5m", "15m", "1h", "6h", "24h", "7d", "all", "custom"].map((value) => <option key={value} value={value}>{t(`logs.range.${value}`)}</option>)}</select>
        <select aria-label={t("logs.level")} value={filters.priority.join(",")} onChange={(event) => setFilters((current) => ({ ...current, priority: event.target.value ? event.target.value.split(",").map(Number) : [] }))}><option value="">{t("logs.allLevels")}</option><option value="0,1,2,3">{t("logs.errors")}</option><option value="0,1,2,3,4">{t("logs.warningsAndErrors")}</option>{severityNames.map((name, index) => <option key={name} value={index}>{t(`logs.severity.${name}`)}</option>)}</select>
        <button type="button" className={filtersOpen ? "active" : ""} onClick={() => setFiltersOpen((value) => !value)}><Filter />{t("logs.filters")}<span>{activeFilters}</span></button>
        <button type="button" title={t("action.refresh")} aria-label={t("action.refresh")} onClick={() => void load(false)}><RefreshCw className={loading ? "spin" : ""} /></button>
        {sources?.capabilities.live && <button type="button" className={live ? "live active" : ""} onClick={() => setLive((value) => !value)}><span />{t("logs.live")}</button>}
        {live && <button type="button" onClick={() => paused ? resume() : setPaused(true)}>{paused ? <CirclePlay /> : <CirclePause />}{paused ? t("logs.resume") : t("logs.pause")}{pending.length > 0 && <span>{pending.length}</span>}</button>}
        <div className="logs-export"><Download /><select aria-label={t("logs.export")} defaultValue="" onChange={(event) => { const value = event.target.value as "txt" | "json" | "jsonl" | "csv"; if (value) void exportView(value); event.target.value = ""; }}><option value="" disabled>{t("logs.export")}</option>{["txt", "json", "jsonl", "csv"].map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></div>
        <button type="button" className={wrap ? "active" : ""} title={t("logs.wrap")} aria-pressed={wrap} onClick={() => setWrap((value) => !value)}><WrapText /></button>
        <button type="button" className={autoScroll ? "active" : ""} title={t("logs.autoScroll")} aria-pressed={autoScroll} onClick={() => setAutoScroll((value) => !value)}><Clock3 /></button>
        <button type="button" onClick={() => setViewMode((value) => value === "compact" ? "table" : "compact")}><Settings2 />{t(`logs.view.${viewMode}`)}</button>
      </header>

      {filtersOpen && <FilterPanel filters={filters} range={range} boots={boots} services={services} containers={containers} t={t} onChange={setFilters} onRange={setRange} onClose={() => setFiltersOpen(false)} onClear={clearFilters} onErrors={onlyErrors} onCurrentBoot={currentBoot} />}
      {error && <div className="logs-error" role="alert"><AlertCircle /><span>{error}</span><button onClick={() => void load(false)}>{t("action.retry")}</button></div>}
      <div className={`logs-list ${viewMode} ${wrap ? "wrap" : ""}`} ref={listRef} role="list" aria-label={t("logs.entries")} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
        {viewMode === "table" && <div className="logs-table-head"><span>{t("logs.timestamp")}</span><span>{t("logs.level")}</span><span>{t("logs.source")}</span><span>PID</span><span>{t("logs.message")}</span></div>}
        {loading && !entries.length ? <div className="loading-state"><RefreshCw className="spin" />{t("status.loading")}</div> : !entries.length ? <div className="empty-state">{t("logs.noEntries")}</div> : <div className="logs-virtual" style={{ height: entries.length * rowHeight }}>{visible.map((entry, offset) => <LogRow key={entry.id} entry={entry} query={query} mode={viewMode} selected={selected?.id === entry.id} t={t} style={{ transform: `translateY(${(start + offset) * rowHeight}px)`, height: rowHeight }} onClick={() => setSelected(entry)} />)}</div>}
      </div>
      {cursor && <footer className="logs-pagination"><span>{t("logs.loadedEntries").replace("{count}", String(entries.length))}</span><button disabled={loadingMore} onClick={() => void load(true)}>{loadingMore ? <RefreshCw className="spin" /> : <ChevronRight />}{t("logs.loadOlder")}</button></footer>}
    </main>
    {selected && <LogDetails entry={selected} t={t} onClose={() => setSelected(null)} onFilter={(key, value) => {
      if (key === "unit") { setSource(`service:${value}`); setFilters((current) => ({ ...current, unit: value })); }
      else if (key === "pid") setFilters((current) => ({ ...current, pid: value }));
      else if (key === "uid") setFilters((current) => ({ ...current, uid: value }));
      else if (key === "identifier") setFilters((current) => ({ ...current, identifier: value }));
      else if (key === "hostname") setFilters((current) => ({ ...current, hostname: value }));
    }} />}
  </section>;
}

function SourceTree({ groups, services, containers, selected, t, onChoose }: { groups: LogSourceGroup[]; services: LogService[]; containers: LogContainer[]; selected: string; t: Translate; onChoose: (value: string) => void }) {
  return <nav className="logs-source-tree" aria-label={t("logs.sources")}>{groups.map((group) => <details key={group.id} open><summary>{sourceIcons[group.id] || <FileText />}<span>{t(`logs.group.${group.id}`)}</span><ChevronRight /></summary><div>{group.items.map((item) => <button key={item.id} className={selected === item.id ? "active" : ""} disabled={!item.available} title={!item.available ? t(`logs.status.${item.status}`) : item.label} onClick={() => onChoose(item.id)}><span className={`source-state ${item.status}`} />{item.label}{!item.available && <small>{t(`logs.status.${item.status}`)}</small>}</button>)}{group.id === "services" && services.map((service) => <button key={service.unit} className={selected === `service:${service.unit}` ? "active" : ""} onClick={() => onChoose(`service:${service.unit}`)}><span className={`source-state ${service.active}`} />{service.unit}<small>{service.description}</small></button>)}{group.id === "containers" && containers.map((container) => <button key={container.id} className={selected === `container:${container.id}` ? "active" : ""} onClick={() => onChoose(`container:${container.id}`)}><span className={`source-state ${container.state}`} />{container.name}<small>{container.image}</small></button>)}</div></details>)}</nav>;
}

function FilterPanel({ filters, range, boots, services, containers, t, onChange, onRange, onClose, onClear, onErrors, onCurrentBoot }: { filters: Filters; range: RangeValue; boots: LogBoot[]; services: LogService[]; containers: LogContainer[]; t: Translate; onChange: React.Dispatch<React.SetStateAction<Filters>>; onRange: (value: RangeValue) => void; onClose: () => void; onClear: () => void; onErrors: () => void; onCurrentBoot: () => void }) {
  const field = (key: keyof Filters, label: string, type = "text") => <label><span>{label}</span><input type={type} value={String(filters[key])} onChange={(event) => onChange((current) => ({ ...current, [key]: event.target.value }))} /></label>;
  const toggle = (key: "regex" | "case_sensitive" | "negate" | "message_only", label: string) => <label className="logs-filter-toggle"><input type="checkbox" checked={filters[key]} onChange={(event) => onChange((current) => ({ ...current, [key]: event.target.checked }))} />{label}</label>;
  return <aside className="logs-filter-panel" aria-label={t("logs.filters")}><header><div><Filter /><strong>{t("logs.filters")}</strong></div><button aria-label={t("action.close")} onClick={onClose}><X /></button></header><div className="logs-filter-grid"><label><span>{t("logs.service")}</span><select value={filters.unit} onChange={(event) => onChange((current) => ({ ...current, unit: event.target.value }))}><option value="">{t("filter.all")}</option>{services.map((item) => <option key={item.unit}>{item.unit}</option>)}</select></label><label><span>{t("logs.boot")}</span><select value={filters.boot_id} onChange={(event) => onChange((current) => ({ ...current, boot_id: event.target.value }))}><option value="">{t("filter.all")}</option>{boots.map((item) => <option key={item.id} value={item.id}>{item.current ? t("logs.currentBoot") : `#${item.index}`} · {item.id.slice(0, 8)}</option>)}</select></label><label><span>{t("logs.container")}</span><select value={filters.container_id} onChange={(event) => onChange((current) => ({ ...current, container_id: event.target.value }))}><option value="">{t("filter.all")}</option>{containers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{field("pid", "PID", "number")}{field("uid", "UID", "number")}{field("username", t("logs.user"))}{field("group", t("logs.userGroup"))}{field("hostname", t("logs.hostname"))}{field("identifier", t("logs.identifier"))}{field("transport", t("logs.transport"))}{field("device", t("logs.device"))}{range === "custom" && <>{field("since", t("logs.since"), "datetime-local")}{field("until", t("logs.until"), "datetime-local")}</>}</div><div className="logs-filter-options">{toggle("regex", t("logs.regex"))}{toggle("case_sensitive", t("logs.caseSensitive"))}{toggle("negate", t("logs.negate"))}{toggle("message_only", t("logs.messageOnly"))}</div><footer><button onClick={onClear}>{t("logs.clearFilters")}</button><button onClick={onErrors}>{t("logs.onlyErrors")}</button><button onClick={onCurrentBoot}>{t("logs.currentBoot")}</button><button className="button-primary" onClick={() => { if (range === "custom") onRange("custom"); onClose(); }}>{t("action.apply")}</button></footer></aside>;
}

function originalLevel(entry: LogEntry) {
  return {
    priority: entry.original_priority ?? entry.priority,
    severity: entry.original_severity ?? entry.severity,
  };
}

function entrySummary(entry: LogEntry) {
  if (entry.severity_reason !== "python_traceback" && !entry.message.includes("Traceback (most recent call last):")) return entry.message;
  const lines = entry.message.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return [...lines].reverse().find((line) => /^[\w.]*\w(?:Error|Exception|Fault|Failure):/.test(line)) || lines[lines.length - 1] || entry.message;
}

function LogRow({ entry, query, mode, selected, t, style, onClick }: { entry: LogEntry; query: string; mode: ViewMode; selected: boolean; t: Translate; style: React.CSSProperties; onClick: () => void }) {
  const parsedTime = entry.timestamp ? new Date(entry.timestamp) : null;
  const time = parsedTime && !Number.isNaN(parsedTime.getTime()) ? `${parsedTime.toLocaleString(undefined, { hour12: false })}.${String(parsedTime.getMilliseconds()).padStart(3, "0")}` : entry.timestamp || "—";
  const summary = entrySummary(entry);
  return <button style={style} role="listitem" aria-expanded={selected} className={`log-row severity-${entry.severity} ${entry.severity_reason === "python_traceback" ? "traceback" : ""} ${selected ? "selected" : ""}`} onClick={onClick}>{mode === "table" ? <><time>{time}</time><span className="log-severity">{t(`logs.severity.${entry.severity}`)}</span><span title={entry.unit || entry.identifier || entry.source}>{entry.unit || entry.identifier || entry.source}</span><span>{entry.pid ?? "—"}</span><span className="log-message"><Highlight value={summary} query={query} /></span></> : <><time>{time}</time><span className="log-severity">{t(`logs.severity.${entry.severity}`)}</span><strong>{entry.unit || entry.identifier || entry.source}</strong>{entry.pid !== null && <small>PID {entry.pid}</small>}<span className="log-message"><Highlight value={summary} query={query} /></span></>}</button>;
}

function Highlight({ value, query }: { value: string; query: string }) {
  const needle = query.replace(/^"|"$/g, "").split(/\s+/)[0];
  if (!needle) return value;
  const index = value.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase());
  if (index < 0) return value;
  return <>{value.slice(0, index)}<mark>{value.slice(index, index + needle.length)}</mark>{value.slice(index + needle.length)}</>;
}

function LogDetails({ entry, t, onClose, onFilter }: { entry: LogEntry; t: Translate; onClose: () => void; onFilter: (key: "unit" | "pid" | "uid" | "identifier" | "hostname", value: string) => void }) {
  const copy = (value: string) => void navigator.clipboard?.writeText(value);
  const original = originalLevel(entry);
  const known = [
    [t("logs.effectiveLevel"), `${entry.severity} (${entry.priority})`],
    [t("logs.originalLevel"), `${original.severity} (${original.priority})`],
    ["timestamp", entry.timestamp], ["unit", entry.unit], ["identifier", entry.identifier], ["pid", entry.pid],
    ["uid", entry.uid], ["hostname", entry.hostname], ["cursor", entry.cursor],
  ] as const;
  return <aside className="logs-details"><header><div><small>{t("logs.entryDetails")}</small><strong>{entry.unit || entry.identifier || entry.source}</strong></div><button aria-label={t("action.close")} onClick={onClose}><X /></button></header>{entry.severity_inferred && <p className="logs-severity-correction">{t("logs.severityCorrected")} {entry.severity_reason ? `(${t(`logs.reason.${entry.severity_reason}`)})` : ""}</p>}<section className="logs-detail-message"><pre>{entry.message}</pre><button onClick={() => copy(entry.message)}><Copy />{t("logs.copyMessage")}</button></section><div className="logs-detail-actions"><button onClick={() => copy(`${entry.timestamp || ""} [${entry.severity}/${entry.priority}; original=${original.severity}/${original.priority}] ${entry.unit || entry.identifier || entry.source}: ${entry.message}`)}><Copy />{t("logs.copyRecord")}</button><button onClick={() => copy(JSON.stringify(entry, null, 2))}><Copy />{t("logs.copyJson")}</button>{entry.unit && <button onClick={() => onFilter("unit", entry.unit)}><ServerCog />{t("logs.sameService")}</button>}{entry.pid !== null && <button onClick={() => onFilter("pid", String(entry.pid))}><Terminal />{t("logs.sameProcess")}</button>}</div><dl>{known.filter(([, value]) => value !== "" && value !== null).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{String(value)}</code>{["unit", "pid", "uid", "identifier", "hostname"].includes(key) && <button aria-label={`${t("logs.filterBy")}: ${key}`} onClick={() => onFilter(key as "unit" | "pid" | "uid" | "identifier" | "hostname", String(value))}><Filter /></button>}</dd></div>)}</dl><details open><summary>{t("logs.allFields")}</summary><dl>{Object.entries(entry.fields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{typeof value === "string" ? value : JSON.stringify(value)}</code></dd></div>)}</dl></details><details><summary>{t("logs.rawJson")}</summary><pre>{JSON.stringify(entry, null, 2)}</pre></details></aside>;
}
