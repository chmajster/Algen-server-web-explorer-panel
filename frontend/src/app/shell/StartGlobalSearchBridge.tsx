import { Box, FolderSearch2, Play, Search, ServerCog, Settings2, SquareTerminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { WebNAS } from "./WebNASShell";
import type { SearchResult } from "./managers";
import "./start-global-search.css";

const icons: Record<SearchResult["category"], React.ReactNode> = {
  application: <Play />,
  file: <FolderSearch2 />,
  directory: <FolderSearch2 />,
  service: <ServerCog />,
  container: <Box />,
  setting: <Settings2 />,
  action: <SquareTerminal />,
};

export function StartGlobalSearchBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const searchSequence = useRef(0);

  useEffect(() => {
    let input: HTMLInputElement | null = null;
    let launcher: HTMLElement | null = null;
    const onInput = () => setQuery(input?.value || "");
    const find = () => {
      const nextLauncher = document.querySelector<HTMLElement>(".app-launcher");
      const nextInput = nextLauncher?.querySelector<HTMLInputElement>(".launcher-search input") || null;
      if (nextLauncher === launcher && nextInput === input) return;
      input?.removeEventListener("input", onInput);
      launcher?.classList.remove("webnas-global-search-active");
      launcher = nextLauncher;
      input = nextInput;
      if (launcher && input) {
        setHost(launcher);
        setQuery(input.value);
        input.addEventListener("input", onInput);
      } else {
        setHost(null);
        setQuery("");
      }
    };
    find();
    const observer = new MutationObserver(find);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      input?.removeEventListener("input", onInput);
      launcher?.classList.remove("webnas-global-search-active");
    };
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    host?.classList.toggle("webnas-global-search-active", normalized.length > 0);
    if (!normalized) { setResults([]); setLoading(false); return; }
    const sequence = ++searchSequence.current;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void WebNAS.search.search(normalized).then((items) => {
        if (sequence !== searchSequence.current) return;
        const unique = new Map<string, SearchResult>();
        for (const item of items) if (!unique.has(item.id)) unique.set(item.id, item);
        setResults([...unique.values()].slice(0, 60));
      }).finally(() => { if (sequence === searchSequence.current) setLoading(false); });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [host, query]);

  if (!host || !query.trim()) return null;
  return createPortal(<section className="start-global-results" aria-label="Globalne wyniki wyszukiwania">
    <header><Search /><strong>Wyniki WebNAS</strong><small>{loading ? "Wyszukiwanie…" : `${results.length} wyników`}</small></header>
    {!loading && results.length === 0 && <p className="start-global-empty">Brak wyników.</p>}
    <div className="start-global-list">
      {results.map((item) => <button key={item.id} type="button" onClick={() => { void Promise.resolve(item.run()); }}>
        <span className="start-global-icon">{icons[item.category]}</span>
        <span><strong>{item.title}</strong><small>{item.subtitle || item.category}</small></span>
        <em>{item.category}</em>
      </button>)}
    </div>
  </section>, host);
}
