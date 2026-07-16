import {
  AlertCircle, Ban, Boxes, CheckCircle2, ChevronLeft, ChevronRight, Clock3,
  FileClock, Info, LogIn, RefreshCw, Search, Settings2, ShieldCheck, UserRound
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api, type ActivityCategory, type ActivityEvent, type ActivityResponse,
  type ActivityStatus, type ActivitySummary
} from "../../api";
import type { Translate } from "../../app/types";

const categories: ActivityCategory[] = ["login", "file", "configuration", "administration", "module"];
const statuses: ActivityStatus[] = ["success", "failure", "info", "queued", "cancelled"];

function CategoryIcon({ category }: { category: ActivityCategory }) {
  const Icon = category === "login" ? LogIn : category === "file" ? FileClock : category === "configuration" ? Settings2 : category === "administration" ? ShieldCheck : Boxes;
  return <Icon aria-hidden="true" />;
}

function StatusIcon({ status }: { status: ActivityStatus }) {
  const Icon = status === "success" ? CheckCircle2 : status === "failure" ? AlertCircle : status === "queued" ? Clock3 : status === "cancelled" ? Ban : Info;
  return <Icon aria-hidden="true" />;
}

function translatedAction(t: Translate, action: string) {
  const direct = t(`activity.action.${action}`);
  if (direct !== `activity.action.${action}`) return direct;
  const managed = t(`managed.action.${action}`);
  if (managed !== `managed.action.${action}`) return managed;
  return action.replace(/_/g, " ");
}

export function ActivityCenter({ locale, t }: { locale: "pl-PL" | "en-US"; t: Translate }) {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [summary, setSummary] = useState<ActivitySummary | null>(null);
  const [category, setCategory] = useState<ActivityCategory | "">("");
  const [status, setStatus] = useState<ActivityStatus | "">("");
  const [actor, setActor] = useState("");
  const [debouncedActor, setDebouncedActor] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedActor(actor.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [actor]);

  useEffect(() => setPage(1), [category, status, debouncedActor, debouncedSearch]);

  const refresh = useCallback(async (quiet = false) => {
    const id = ++requestId.current;
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const [events, totals] = await Promise.all([
        api.activity({ category, status, actor: debouncedActor, search: debouncedSearch, page, page_size: 50 }),
        api.activitySummary(),
      ]);
      if (requestId.current !== id) return;
      setData(events);
      setSummary(totals);
      if (events.scope === "own") setActor("");
    } catch (reason) {
      if (requestId.current === id) setError(reason instanceof Error ? reason.message : t("status.error"));
    } finally {
      if (requestId.current === id) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [category, debouncedActor, debouncedSearch, page, status, t]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(true); }, 15_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const categoryCards = useMemo(() => categories.map((item) => ({ category: item, count: summary?.categories[item] || 0 })), [summary]);

  return <section className="activity-app" aria-label={t("activity.title")}>
    <header className="activity-header">
      <div>
        <h2>{t("activity.title")}</h2>
        <p>{t(data?.scope === "global" ? "activity.subtitleGlobal" : "activity.subtitleOwn")}</p>
      </div>
      <button type="button" onClick={() => void refresh(true)} disabled={refreshing} aria-label={t("action.refresh")}>
        <RefreshCw className={refreshing ? "spin" : ""} />
        <span>{t("action.refresh")}</span>
      </button>
    </header>

    <div className="activity-summary" aria-label={t("activity.summary")}>
      {categoryCards.map((item) => <button
        type="button"
        key={item.category}
        className={category === item.category ? "selected" : ""}
        aria-pressed={category === item.category}
        onClick={() => setCategory((current) => current === item.category ? "" : item.category)}
      >
        <CategoryIcon category={item.category} />
        <span>{t(`activity.category.${item.category}`)}</span>
        <strong>{item.count}</strong>
      </button>)}
    </div>

    <div className="activity-filters" role="search">
      <label className="activity-search">
        <span>{t("activity.search")}</span>
        <div><Search aria-hidden="true" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("activity.searchPlaceholder")} /></div>
      </label>
      <label>
        <span>{t("activity.category")}</span>
        <select value={category} onChange={(event) => setCategory(event.target.value as ActivityCategory | "")}>
          <option value="">{t("activity.allCategories")}</option>
          {categories.map((item) => <option key={item} value={item}>{t(`activity.category.${item}`)}</option>)}
        </select>
      </label>
      <label>
        <span>{t("activity.status")}</span>
        <select value={status} onChange={(event) => setStatus(event.target.value as ActivityStatus | "")}>
          <option value="">{t("activity.allStatuses")}</option>
          {statuses.map((item) => <option key={item} value={item}>{t(`activity.status.${item}`)}</option>)}
        </select>
      </label>
      {data?.scope === "global" && <label>
        <span>{t("activity.actor")}</span>
        <div className="activity-actor"><UserRound aria-hidden="true" /><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder={t("activity.actorPlaceholder")} /></div>
      </label>}
    </div>

    {error && <div className="activity-error" role="alert"><AlertCircle />{error}<button type="button" onClick={() => void refresh()}>{t("action.retry")}</button></div>}

    <div className="activity-feed" aria-busy={loading}>
      {loading && !data ? <div className="activity-empty">{t("status.loading")}</div> : data?.items.length ? <ol aria-live="polite">
        {data.items.map((event) => <ActivityRow key={event.id} event={event} locale={locale} showActor={data.scope === "global"} t={t} />)}
      </ol> : <div className="activity-empty">{t("activity.empty")}</div>}
    </div>

    <footer className="activity-footer">
      <span>{t("activity.results").replace("{count}", String(data?.total || 0))}</span>
      <div>
        <button type="button" disabled={!data || data.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} aria-label={t("action.previous")}><ChevronLeft /></button>
        <span>{t("activity.page").replace("{page}", String(data?.page || 1)).replace("{pages}", String(data?.total_pages || 1))}</span>
        <button type="button" disabled={!data || data.page >= data.total_pages} onClick={() => setPage((current) => current + 1)} aria-label={t("action.next")}><ChevronRight /></button>
      </div>
    </footer>
  </section>;
}

function ActivityRow({ event, locale, showActor, t }: { event: ActivityEvent; locale: string; showActor: boolean; t: Translate }) {
  return <li className={`activity-row status-${event.status}`}>
    <div className="activity-category-icon"><CategoryIcon category={event.category} /></div>
    <article>
      <header>
        <strong>{translatedAction(t, event.action)}</strong>
        <span className={`activity-status ${event.status}`}><StatusIcon status={event.status} />{t(`activity.status.${event.status}`)}</span>
      </header>
      {event.target && <code title={event.target}>{event.target}</code>}
      {event.summary && <p>{event.summary}</p>}
      <footer>
        {showActor && <span><UserRound aria-hidden="true" />{event.actor}</span>}
        <time dateTime={new Date(event.created_at * 1000).toISOString()}>{new Date(event.created_at * 1000).toLocaleString(locale)}</time>
        <span>{t(`activity.category.${event.category}`)}</span>
      </footer>
    </article>
  </li>;
}
