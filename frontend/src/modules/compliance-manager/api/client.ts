import { request } from "../../../core/api/transport";

export type ComplianceStatus = "pass" | "fail" | "manual" | "error" | "not_applicable";
export type ComplianceSeverity = "critical" | "high" | "medium" | "low" | "info";

export type ComplianceControl = {
  id: string;
  benchmark_id: string;
  benchmark_ref: string;
  profile: string;
  category: string;
  title: string;
  status: ComplianceStatus;
  severity: ComplianceSeverity;
  expected: string;
  actual: string;
  rationale: string;
  remediation: string;
  evidence: Record<string, unknown>;
};

export type CategorySummary = {
  score: number | null;
  passed: number;
  failed: number;
  manual: number;
  error: number;
  not_applicable: number;
  total: number;
};

export type ComplianceSummary = CategorySummary & {
  last_scan: number | null;
  categories: Record<string, CategorySummary>;
};

export type Benchmark = {
  id: string;
  name: string;
  profile: string;
  categories: string[];
  scope: string;
  disclaimer: string;
};

export const complianceClient = {
  summary: () => request<ComplianceSummary>("/api/modules/compliance-manager/summary"),
  controls: (category?: string) => request<{ items: ComplianceControl[]; total: number }>(`/api/modules/compliance-manager/controls${category ? `?category=${encodeURIComponent(category)}` : ""}`),
  benchmarks: () => request<{ items: Benchmark[]; total: number }>("/api/modules/compliance-manager/benchmarks"),
  scan: () => request("/api/modules/compliance-manager/scan", { method: "POST", body: "{}" }),
};
