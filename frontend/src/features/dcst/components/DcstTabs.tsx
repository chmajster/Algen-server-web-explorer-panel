export type DcstTab = "overview" | "services" | "tags" | "ipsets" | "ports" | "utilities";

const tabs: Array<[DcstTab, string]> = [
  ["overview", "Overview"],
  ["services", "Services"],
  ["tags", "Tags"],
  ["ipsets", "IPSets"],
  ["ports", "Ports"],
  ["utilities", "Utilities"],
];

export function DcstTabs({
  active,
  counts,
  onChange,
}: {
  active: DcstTab;
  counts: Partial<Record<DcstTab, number>>;
  onChange: (tab: DcstTab) => void;
}) {
  return <nav className="module-tabs dcst-tabs" aria-label="DCST sections">
    {tabs.map(([id, label]) => <button
      key={id}
      type="button"
      className={active === id ? "active" : ""}
      aria-current={active === id ? "page" : undefined}
      onClick={() => onChange(id)}
    >
      <span>{label}</span>
      {counts[id] !== undefined && <span className="dcst-tab-count">{counts[id]}</span>}
    </button>)}
  </nav>;
}
