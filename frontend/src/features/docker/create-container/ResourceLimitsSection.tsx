import { ChevronDown, ChevronUp, Minus, Plus } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import type { DockerHostResources, DockerResourceLimits, DockerUlimit } from "../../../core/api/contracts";
import type { Translate } from "../../../app/types";
import { ConfigRow } from "./CompactConfig";

export type ResourceProfile = "unlimited" | "minimal" | "light" | "standard" | "performance" | "custom";
export type MemoryUnit = "MB" | "GB";
export type UlimitDraft = { id: number; name: "nofile" | "nproc"; soft: string; hard: string };
export type ResourceLimitsDraft = {
  cpus: string; cpuSharesPreset: "low" | "normal" | "high" | "custom"; cpuShares: string; cpusetCpus: string; cpuPeriod: string; cpuQuota: string;
  memory: string; memoryUnit: MemoryUnit; memorySwap: string; memorySwapUnit: MemoryUnit;
  memoryReservation: string; memoryReservationUnit: MemoryUnit; memorySwappiness: string; shmSize: string; shmSizeUnit: MemoryUnit;
  pids: string; blkioPreset: "low" | "normal" | "high" | "custom"; blkioWeight: string; oomScoreAdj: string; oomKillDisable: boolean;
  ulimits: UlimitDraft[];
};

export const EMPTY_RESOURCE_LIMITS: ResourceLimitsDraft = {
  cpus: "", cpuSharesPreset: "normal", cpuShares: "", cpusetCpus: "", cpuPeriod: "", cpuQuota: "",
  memory: "", memoryUnit: "MB", memorySwap: "", memorySwapUnit: "MB",
  memoryReservation: "", memoryReservationUnit: "MB", memorySwappiness: "", shmSize: "", shmSizeUnit: "MB",
  pids: "", blkioPreset: "normal", blkioWeight: "", oomScoreAdj: "", oomKillDisable: false, ulimits: [],
};

const PROFILES: Record<Exclude<ResourceProfile, "unlimited" | "custom">, Pick<ResourceLimitsDraft, "cpus" | "memory" | "memoryUnit" | "memorySwap" | "memorySwapUnit" | "pids">> = {
  minimal: { cpus: "0.25", memory: "256", memoryUnit: "MB", memorySwap: "512", memorySwapUnit: "MB", pids: "64" },
  light: { cpus: "0.5", memory: "512", memoryUnit: "MB", memorySwap: "1", memorySwapUnit: "GB", pids: "128" },
  standard: { cpus: "1", memory: "1", memoryUnit: "GB", memorySwap: "2", memorySwapUnit: "GB", pids: "256" },
  performance: { cpus: "2", memory: "4", memoryUnit: "GB", memorySwap: "8", memorySwapUnit: "GB", pids: "512" },
};

function toMb(value: string, unit: MemoryUnit): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * (unit === "GB" ? 1024 : 1)) : null;
}

function fromMb(value: number | null | undefined): { value: string; unit: MemoryUnit } {
  if (!value) return { value: "", unit: "MB" };
  return value >= 1024 && value % 1024 === 0 ? { value: String(value / 1024), unit: "GB" } : { value: String(value), unit: "MB" };
}

function numberValue(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function resourceLimitsFromPayload(value?: DockerResourceLimits): ResourceLimitsDraft {
  const memory = fromMb(value?.memory_mb);
  const swap = fromMb(value?.memory_swap_mb);
  const reservation = fromMb(value?.memory_reservation_mb);
  const shm = fromMb(value?.shm_size_mb);
  const shares = value?.cpu_shares;
  const blkio = value?.blkio_weight;
  return {
    ...EMPTY_RESOURCE_LIMITS,
    cpus: value?.cpus == null ? "" : String(value.cpus),
    cpuSharesPreset: shares === 512 ? "low" : shares === 1024 ? "normal" : shares === 2048 ? "high" : shares == null ? "normal" : "custom",
    cpuShares: shares == null ? "" : String(shares), cpusetCpus: value?.cpuset_cpus || "",
    cpuPeriod: value?.cpu_period == null ? "" : String(value.cpu_period), cpuQuota: value?.cpu_quota == null ? "" : String(value.cpu_quota),
    memory: memory.value, memoryUnit: memory.unit, memorySwap: swap.value, memorySwapUnit: swap.unit,
    memoryReservation: reservation.value, memoryReservationUnit: reservation.unit,
    memorySwappiness: value?.memory_swappiness == null ? "" : String(value.memory_swappiness), shmSize: shm.value, shmSizeUnit: shm.unit,
    pids: value?.pids == null ? "" : String(value.pids),
    blkioPreset: blkio === 100 ? "low" : blkio === 500 ? "normal" : blkio === 1000 ? "high" : blkio == null ? "normal" : "custom",
    blkioWeight: blkio == null ? "" : String(blkio), oomScoreAdj: value?.oom_score_adj == null ? "" : String(value.oom_score_adj),
    oomKillDisable: Boolean(value?.oom_kill_disable),
    ulimits: (value?.ulimits || []).map((item, index) => ({ id: index + 1, name: item.name, soft: String(item.soft), hard: String(item.hard) })),
  };
}

export function resourceLimitsPayload(value: ResourceLimitsDraft, enabled: boolean): DockerResourceLimits {
  if (!enabled) return { ulimits: [], oom_kill_disable: false };
  return {
    cpus: numberValue(value.cpus), cpu_shares: numberValue(value.cpuShares), cpuset_cpus: value.cpusetCpus.trim() || null,
    cpu_period: numberValue(value.cpuPeriod), cpu_quota: numberValue(value.cpuQuota),
    memory_mb: toMb(value.memory, value.memoryUnit), memory_swap_mb: toMb(value.memorySwap, value.memorySwapUnit),
    memory_reservation_mb: toMb(value.memoryReservation, value.memoryReservationUnit), memory_swappiness: numberValue(value.memorySwappiness),
    shm_size_mb: toMb(value.shmSize, value.shmSizeUnit), pids: numberValue(value.pids), blkio_weight: numberValue(value.blkioWeight),
    oom_score_adj: numberValue(value.oomScoreAdj), oom_kill_disable: value.oomKillDisable,
    ulimits: value.ulimits.map((item): DockerUlimit => ({ name: item.name, soft: Number(item.soft), hard: Number(item.hard) })),
  };
}

function cpusetValues(value: string): number[] | null {
  if (!/^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$/.test(value)) return null;
  const result: number[] = [];
  for (const item of value.split(",")) {
    const [first, last] = item.includes("-") ? item.split("-").map(Number) : [Number(item), Number(item)];
    if (first > last || last > 65_535) return null;
    for (let cpu = first; cpu <= last; cpu += 1) result.push(cpu);
  }
  return new Set(result).size === result.length ? result : null;
}

export function resourceLimitIssues(value: ResourceLimitsDraft, enabled: boolean, host: DockerHostResources | null, t: Translate): string[] {
  if (!enabled) return [];
  const issues: string[] = [];
  const range = (raw: string, minimum: number, maximum: number, key: string, integer = true) => {
    if (!raw.trim()) return;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum || integer && !Number.isInteger(parsed)) issues.push(t(key));
  };
  range(value.cpus, 0.1, 128, "docker.resources.validation.cpu", false);
  range(value.cpuShares, 2, 262144, "docker.resources.validation.cpuShares");
  range(value.cpuPeriod, 1000, 1000000, "docker.resources.validation.cpuPeriod");
  range(value.cpuQuota, 1000, 1000000000, "docker.resources.validation.cpuQuota");
  range(value.memory, value.memoryUnit === "GB" ? 16 / 1024 : 16, value.memoryUnit === "GB" ? 1024 : 1048576, "docker.resources.validation.memory", false);
  range(value.memorySwap, value.memorySwapUnit === "GB" ? 16 / 1024 : 16, value.memorySwapUnit === "GB" ? 2048 : 2097152, "docker.resources.validation.memorySwap", false);
  range(value.memoryReservation, value.memoryReservationUnit === "GB" ? 16 / 1024 : 16, value.memoryReservationUnit === "GB" ? 1024 : 1048576, "docker.resources.validation.memoryReservation", false);
  range(value.memorySwappiness, 0, 100, "docker.resources.validation.swappiness");
  range(value.shmSize, value.shmSizeUnit === "GB" ? 1 / 1024 : 1, value.shmSizeUnit === "GB" ? 1024 : 1048576, "docker.resources.validation.shm", false);
  range(value.pids, 16, 4194304, "docker.resources.validation.pids");
  range(value.blkioWeight, 10, 1000, "docker.resources.validation.blkio");
  range(value.oomScoreAdj, -1000, 1000, "docker.resources.validation.oomScore");
  const memory = toMb(value.memory, value.memoryUnit);
  const swap = toMb(value.memorySwap, value.memorySwapUnit);
  const reservation = toMb(value.memoryReservation, value.memoryReservationUnit);
  if (swap !== null && memory === null) issues.push(t("docker.resources.validation.swapNeedsMemory"));
  else if (swap !== null && memory !== null && swap < memory) issues.push(t("docker.resources.validation.swapOrder"));
  if (reservation !== null && memory !== null && reservation > memory) issues.push(t("docker.resources.validation.reservationOrder"));
  if (Boolean(value.cpuPeriod) !== Boolean(value.cpuQuota)) issues.push(t("docker.resources.validation.quotaPair"));
  if (value.cpus && value.cpuPeriod) issues.push(t("docker.resources.validation.cpuConflict"));
  if (value.cpusetCpus) {
    const selected = cpusetValues(value.cpusetCpus);
    if (!selected) issues.push(t("docker.resources.validation.cpuset"));
    else if (host?.logical_cpus && Math.max(...selected) >= host.logical_cpus) issues.push(t("docker.resources.validation.cpusetHost"));
  }
  if (value.oomKillDisable && memory === null) issues.push(t("docker.resources.validation.oomNeedsMemory"));
  if (new Set(value.ulimits.map((item) => item.name)).size !== value.ulimits.length) issues.push(t("docker.resources.validation.ulimitDuplicate"));
  for (const item of value.ulimits) {
    const soft = Number(item.soft); const hard = Number(item.hard);
    if (!Number.isInteger(soft) || !Number.isInteger(hard) || soft < 1 || hard < 1 || soft > 4194304 || hard > 4194304 || soft > hard) {
      issues.push(t("docker.resources.validation.ulimit")); break;
    }
  }
  return [...new Set(issues)];
}

export function resourceSummary(value: ResourceLimitsDraft, enabled: boolean, t: Translate): Array<[string, string]> {
  if (!enabled) return [[t("docker.resources.profile"), t("docker.resources.profile.unlimited")]];
  const result: Array<[string, string]> = [];
  const add = (label: string, item: string, suffix = "") => { if (item) result.push([t(label), `${item}${suffix}`]); };
  add("docker.field.cpus", value.cpus, " CPU"); add("docker.resources.cpuset", value.cpusetCpus);
  add("docker.field.memoryMb", value.memory, ` ${value.memoryUnit}`); add("docker.resources.memoryReservation", value.memoryReservation, ` ${value.memoryReservationUnit}`);
  add("docker.field.memorySwapMb", value.memorySwap, ` ${value.memorySwapUnit}`); add("docker.field.pids", value.pids);
  add("docker.resources.shmSize", value.shmSize, ` ${value.shmSizeUnit}`); add("docker.resources.cpuShares", value.cpuShares);
  add("docker.resources.cpuPeriod", value.cpuPeriod, " µs"); add("docker.resources.cpuQuota", value.cpuQuota, " µs");
  add("docker.resources.swappiness", value.memorySwappiness); add("docker.resources.blkioWeight", value.blkioWeight); add("docker.resources.oomScoreAdj", value.oomScoreAdj);
  if (value.oomKillDisable) result.push([t("docker.resources.oomKillDisable"), t("common.yes")]);
  if (value.ulimits.length) result.push([t("docker.resources.ulimits"), value.ulimits.map((item) => `${item.name} ${item.soft}:${item.hard}`).join(", ")]);
  return result;
}

function MemoryInput({ disabled, label, unit, value, t, onUnit, onValue }: { disabled: boolean; label: string; unit: MemoryUnit; value: string; t: Translate; onUnit: (value: MemoryUnit) => void; onValue: (value: string) => void }) {
  return <div className="docker-resource-unit"><input aria-label={label} disabled={disabled} type="number" min="0" step="0.25" value={value} onChange={(event) => onValue(event.target.value)} /><select aria-label={`${label} ${t("docker.resources.unit")}`} disabled={disabled} value={unit} onChange={(event) => onUnit(event.target.value as MemoryUnit)}><option>MB</option><option>GB</option></select></div>;
}

function AdvancedGroup({ active, children, title }: { active: number; children: ReactNode; title: string }) {
  const [open, setOpen] = useState(false); const id = useId();
  return <section className="docker-resource-advanced"><button type="button" aria-label={title} aria-expanded={open} aria-controls={id} onClick={() => setOpen((current) => !current)}>{open ? <ChevronUp /> : <ChevronDown />}<span>{title}</span>{active > 0 && <b>{active}</b>}</button>{open && <div id={id}>{children}</div>}</section>;
}

export function ResourceLimitsSection({ enabled, host, profile, t, value, onEnabled, onProfile, onValue }: {
  enabled: boolean; host: DockerHostResources | null; profile: ResourceProfile; t: Translate; value: ResourceLimitsDraft;
  onEnabled: (enabled: boolean) => void; onProfile: (profile: ResourceProfile) => void; onValue: (value: ResourceLimitsDraft) => void;
}) {
  const update = (changes: Partial<ResourceLimitsDraft>) => { onValue({ ...value, ...changes }); onProfile("custom"); };
  const chooseProfile = (next: ResourceProfile) => {
    onProfile(next);
    if (next === "unlimited") { onEnabled(false); return; }
    onEnabled(true);
    if (next !== "custom") onValue({ ...EMPTY_RESOURCE_LIMITS, ...PROFILES[next] });
  };
  const sharesPreset = (preset: ResourceLimitsDraft["cpuSharesPreset"]) => update({ cpuSharesPreset: preset, cpuShares: preset === "low" ? "512" : preset === "normal" ? "1024" : preset === "high" ? "2048" : value.cpuShares });
  const blkioPreset = (preset: ResourceLimitsDraft["blkioPreset"]) => update({ blkioPreset: preset, blkioWeight: preset === "low" ? "100" : preset === "normal" ? "500" : preset === "high" ? "1000" : value.blkioWeight });
  const addUlimit = () => {
    const name = value.ulimits.some((item) => item.name === "nofile") ? "nproc" : "nofile";
    update({ ulimits: [...value.ulimits, { id: Math.max(0, ...value.ulimits.map((item) => item.id)) + 1, name, soft: "", hard: "" }] });
  };
  const memoryMb = toMb(value.memory, value.memoryUnit);
  const cpuAdvanced = [value.cpuShares, value.cpusetCpus, value.cpuPeriod, value.cpuQuota].filter(Boolean).length;
  const memoryAdvanced = [value.memoryReservation, value.memorySwappiness, value.shmSize, value.oomScoreAdj, value.oomKillDisable ? "yes" : ""].filter(Boolean).length;
  return <div className="docker-resource-limits">
    <ConfigRow label={t("docker.wizard.enableLimits")} description={t("docker.wizard.resourcePolicyHint")}><label className="docker-compact-check"><input type="checkbox" checked={enabled} onChange={(event) => { onEnabled(event.target.checked); onProfile(event.target.checked ? "custom" : "unlimited"); }} />{t("docker.wizard.enableLimits")}</label></ConfigRow>
    <ConfigRow label={t("docker.resources.profile")}><select aria-label={t("docker.resources.profile")} value={enabled ? profile : "unlimited"} onChange={(event) => chooseProfile(event.target.value as ResourceProfile)}>{(["unlimited", "minimal", "light", "standard", "performance", "custom"] as const).map((item) => <option key={item} value={item}>{t(`docker.resources.profile.${item}`)}</option>)}</select></ConfigRow>
    {host && <div className="docker-resource-host"><strong>{t("docker.resources.host")}</strong><span>{host.logical_cpus} CPU</span><span>{(host.memory_bytes / 1024 ** 3).toFixed(1)} GB RAM</span>{host.swap_bytes > 0 && <span>{(host.swap_bytes / 1024 ** 3).toFixed(1)} GB swap</span>}</div>}
    <div className={!enabled ? "docker-limits-disabled" : ""} aria-disabled={!enabled}>
      <h4>{t("docker.resources.basic")}</h4>
      <ConfigRow label={t("docker.field.cpus")} description={t("docker.resources.cpuHint")}><div className="docker-compact-unit"><input aria-label={t("docker.field.cpus")} disabled={!enabled} type="number" min="0.1" max="128" step="0.1" value={value.cpus} onChange={(event) => update({ cpus: event.target.value, cpuPeriod: "", cpuQuota: "" })} /><span>CPU</span></div></ConfigRow>
      {host && Number(value.cpus) > host.logical_cpus && <p className="docker-resource-warning">{t("docker.resources.warning.cpuHost")}</p>}
      <ConfigRow label={t("docker.field.memoryMb")} description={t("docker.resources.memoryHint")}><MemoryInput disabled={!enabled} label={t("docker.field.memoryMb")} unit={value.memoryUnit} value={value.memory} t={t} onUnit={(memoryUnit) => update({ memoryUnit })} onValue={(memory) => update({ memory })} /></ConfigRow>
      {host && memoryMb !== null && memoryMb * 1024 ** 2 > host.memory_bytes && <p className="docker-resource-warning">{t("docker.resources.warning.memoryHost")}</p>}
      <ConfigRow label={t("docker.field.memorySwapMb")} description={t("docker.resources.memorySwapHint")}><MemoryInput disabled={!enabled} label={t("docker.field.memorySwapMb")} unit={value.memorySwapUnit} value={value.memorySwap} t={t} onUnit={(memorySwapUnit) => update({ memorySwapUnit })} onValue={(memorySwap) => update({ memorySwap })} /></ConfigRow>
      <ConfigRow label={t("docker.field.pids")} description={t("docker.resources.pidsHint")}><input aria-label={t("docker.field.pids")} disabled={!enabled} type="number" min="16" max="4194304" step="1" list="docker-pids-presets" value={value.pids} onChange={(event) => update({ pids: event.target.value })} /><datalist id="docker-pids-presets">{[64, 128, 256, 512, 1024].map((item) => <option key={item} value={item} />)}</datalist></ConfigRow>
      {host?.capabilities.advanced_cpu && <AdvancedGroup active={cpuAdvanced} title={t("docker.resources.advancedCpu")}>
        <ConfigRow label={t("docker.resources.cpuPriority")} description={t("docker.resources.cpuSharesHint")}><div className="docker-resource-preset"><select aria-label={t("docker.resources.cpuPriority")} disabled={!enabled} value={value.cpuSharesPreset} onChange={(event) => sharesPreset(event.target.value as ResourceLimitsDraft["cpuSharesPreset"])}>{(["low", "normal", "high", "custom"] as const).map((item) => <option key={item} value={item}>{t(`docker.resources.priority.${item}`)}</option>)}</select>{value.cpuSharesPreset === "custom" && <input aria-label={t("docker.resources.cpuShares")} disabled={!enabled} type="number" min="2" max="262144" value={value.cpuShares} onChange={(event) => update({ cpuShares: event.target.value })} />}</div></ConfigRow>
        <ConfigRow label={t("docker.resources.cpuset")} description={t("docker.resources.cpusetHint")}><input aria-label={t("docker.resources.cpuset")} disabled={!enabled} value={value.cpusetCpus} onChange={(event) => update({ cpusetCpus: event.target.value })} placeholder="0,2,4-6" /></ConfigRow>
        <ConfigRow label={t("docker.resources.cpuPeriod")} description={t("docker.resources.cpuQuotaHint")}><div className="docker-compact-unit"><input aria-label={t("docker.resources.cpuPeriod")} disabled={!enabled} type="number" min="1000" max="1000000" value={value.cpuPeriod} onChange={(event) => update({ cpuPeriod: event.target.value, cpus: "" })} /><span>µs</span></div></ConfigRow>
        <ConfigRow label={t("docker.resources.cpuQuota")}><div className="docker-compact-unit"><input aria-label={t("docker.resources.cpuQuota")} disabled={!enabled} type="number" min="1000" max="1000000000" value={value.cpuQuota} onChange={(event) => update({ cpuQuota: event.target.value, cpus: "" })} /><span>µs</span></div></ConfigRow>
      </AdvancedGroup>}
      <AdvancedGroup active={memoryAdvanced} title={t("docker.resources.advancedMemory")}>
        <ConfigRow label={t("docker.resources.memoryReservation")} description={t("docker.resources.memoryReservationHint")}><MemoryInput disabled={!enabled} label={t("docker.resources.memoryReservation")} unit={value.memoryReservationUnit} value={value.memoryReservation} t={t} onUnit={(memoryReservationUnit) => update({ memoryReservationUnit })} onValue={(memoryReservation) => update({ memoryReservation })} /></ConfigRow>
        <ConfigRow label={t("docker.resources.shmSize")} description={t("docker.resources.shmHint")}><MemoryInput disabled={!enabled} label={t("docker.resources.shmSize")} unit={value.shmSizeUnit} value={value.shmSize} t={t} onUnit={(shmSizeUnit) => update({ shmSizeUnit })} onValue={(shmSize) => update({ shmSize })} /></ConfigRow>
        {host?.capabilities.memory_swappiness && <ConfigRow label={t("docker.resources.swappiness")} description={t("docker.resources.swappinessHint")}><input aria-label={t("docker.resources.swappiness")} disabled={!enabled} type="number" min="0" max="100" value={value.memorySwappiness} onChange={(event) => update({ memorySwappiness: event.target.value })} /></ConfigRow>}
        {host?.capabilities.oom_controls && <><ConfigRow label={t("docker.resources.oomScoreAdj")} description={t("docker.resources.oomScoreHint")}><input aria-label={t("docker.resources.oomScoreAdj")} disabled={!enabled} type="number" min="-1000" max="1000" value={value.oomScoreAdj} onChange={(event) => update({ oomScoreAdj: event.target.value })} /></ConfigRow>{Number(value.oomScoreAdj) < 0 && <p className="docker-resource-warning">{t("docker.resources.warning.negativeOom")}</p>}<ConfigRow label={t("docker.resources.oomKillDisable")} description={t("docker.resources.oomDisableHint")}><label className="docker-compact-check"><input type="checkbox" disabled={!enabled} checked={value.oomKillDisable} onChange={(event) => update({ oomKillDisable: event.target.checked })} />{t("docker.resources.oomKillDisable")}</label></ConfigRow>{value.oomKillDisable && <p className="docker-resource-warning danger">{t("docker.resources.warning.oomDisable")}</p>}</>}
      </AdvancedGroup>
      {host?.capabilities.blkio_weight && <AdvancedGroup active={value.blkioWeight ? 1 : 0} title={t("docker.resources.blockIo")}><ConfigRow label={t("docker.resources.blkioPriority")} description={t("docker.resources.blkioHint")}><div className="docker-resource-preset"><select aria-label={t("docker.resources.blkioPriority")} disabled={!enabled} value={value.blkioPreset} onChange={(event) => blkioPreset(event.target.value as ResourceLimitsDraft["blkioPreset"])}>{(["low", "normal", "high", "custom"] as const).map((item) => <option key={item} value={item}>{t(`docker.resources.priority.${item}`)}</option>)}</select>{value.blkioPreset === "custom" && <input aria-label={t("docker.resources.blkioWeight")} disabled={!enabled} type="number" min="10" max="1000" value={value.blkioWeight} onChange={(event) => update({ blkioWeight: event.target.value })} />}</div></ConfigRow></AdvancedGroup>}
      {host?.capabilities.ulimits && <AdvancedGroup active={value.ulimits.length} title={t("docker.resources.ulimits")}><p className="docker-compact-hint">{t("docker.resources.ulimitsHint")}</p><div className="docker-ulimit-editor">{value.ulimits.map((item) => <div className="docker-ulimit-row" key={item.id}><select aria-label={t("docker.resources.ulimitType")} disabled={!enabled} value={item.name} onChange={(event) => update({ ulimits: value.ulimits.map((row) => row.id === item.id ? { ...row, name: event.target.value as UlimitDraft["name"] } : row) })}><option value="nofile" disabled={value.ulimits.some((row) => row.id !== item.id && row.name === "nofile")}>nofile</option><option value="nproc" disabled={value.ulimits.some((row) => row.id !== item.id && row.name === "nproc")}>nproc</option></select><input aria-label={t("docker.resources.ulimitSoft")} disabled={!enabled} type="number" min="1" value={item.soft} onChange={(event) => update({ ulimits: value.ulimits.map((row) => row.id === item.id ? { ...row, soft: event.target.value } : row) })} placeholder={t("docker.resources.ulimitSoft")} /><input aria-label={t("docker.resources.ulimitHard")} disabled={!enabled} type="number" min="1" value={item.hard} onChange={(event) => update({ ulimits: value.ulimits.map((row) => row.id === item.id ? { ...row, hard: event.target.value } : row) })} placeholder={t("docker.resources.ulimitHard")} /><button type="button" aria-label={t("action.delete")} onClick={() => update({ ulimits: value.ulimits.filter((row) => row.id !== item.id) })}><Minus /></button></div>)}<button className="docker-compact-add" type="button" disabled={!enabled || value.ulimits.length >= 2} onClick={addUlimit}><Plus />{t("docker.resources.addUlimit")}</button></div></AdvancedGroup>}
    </div>
  </div>;
}
