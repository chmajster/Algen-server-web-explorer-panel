import { useId } from "react";

import { clampPercent, usageLevel } from "./monitorUtils";

export type ChartSeries = {
  label: string;
  values: number[];
};

function points(values: number[], maximum: number): string {
  if (values.length === 0) return "";
  return values.map((value, index) => {
    const x = values.length === 1 ? 0 : (index * 100) / (values.length - 1);
    const y = 34 - (Math.max(0, value) * 30) / maximum;
    return `${x},${Math.max(2, Math.min(34, y))}`;
  }).join(" ");
}

export function ResourceChart({ series, label, compact = false, maximum }: { series: ChartSeries[]; label: string; compact?: boolean; maximum?: number }) {
  const id = useId().replace(/:/g, "");
  const derivedMaximum = maximum || Math.max(1, ...series.flatMap((item) => item.values));
  const visibleSeries = series.filter((item) => item.values.length > 0);

  return <div className={`monitor-chart ${compact ? "compact" : ""}`}>
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label={label}>
      <line className="monitor-chart-grid" x1="0" x2="100" y1="18" y2="18" />
      {visibleSeries.map((item, index) => {
        const linePoints = points(item.values, derivedMaximum);
        const fillPoints = linePoints ? `0,36 ${linePoints} 100,36` : "";
        const gradientId = `${id}-${index}`;
        return <g className={`monitor-chart-series monitor-chart-series-${index}`} key={`${item.label}-${index}`}>
          <defs><linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" /><stop offset="100%" /></linearGradient></defs>
          {fillPoints && <polygon className="monitor-chart-fill" fill={`url(#${gradientId})`} points={fillPoints} />}
          <polyline className="monitor-chart-line" points={linePoints} />
        </g>;
      })}
    </svg>
    {series.length > 1 && <div className="monitor-chart-legend" aria-hidden="true">{series.map((item, index) => <span className={`series-${index}`} key={`${item.label}-${index}`}>{item.label}</span>)}</div>}
  </div>;
}

export function UsageBar({ percent, label, compact = false }: { percent: number; label: string; compact?: boolean }) {
  const value = clampPercent(percent);
  return <div className={`monitor-usage ${usageLevel(value)} ${compact ? "compact" : ""}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}>
    <span style={{ width: `${value}%` }} />
  </div>;
}
