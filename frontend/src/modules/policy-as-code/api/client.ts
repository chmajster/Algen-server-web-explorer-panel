import { request } from "../../../core/api/transport";

export type PolicyFormat = "yaml" | "json";

export type PolicyListItem = {
  id: string;
  name: string;
  description: string;
  labels: Record<string, string>;
  enabled: boolean;
  rule_count: number;
  format: PolicyFormat;
  modified_at: number;
  valid: boolean;
  error: string | null;
};

export type PolicyRecord = PolicyListItem & { source: string };

export type PolicySummary = {
  total: number;
  enabled: number;
  disabled: number;
  invalid: number;
  rules: number;
  formats: { yaml: number; json: number };
};

export type PolicyValidation = {
  valid: boolean;
  id: string;
  enabled: boolean;
  rule_count: number;
  document: Record<string, unknown>;
};

export type PolicyRuleResult = {
  id: string;
  severity: string;
  description: string;
  message: string;
  status: "pass" | "fail" | "error";
  error: string | null;
  evidence: Array<Record<string, unknown>>;
};

export type PolicyEvaluation = {
  policy_id?: string;
  scope?: string;
  compliant: boolean;
  score: number;
  passed: number;
  failed: number;
  errors: number;
  total: number;
  results?: PolicyRuleResult[];
  policies?: PolicyEvaluation[];
  invalid_policies?: Array<{ id: string; error: string }>;
};

const sourceBody = (format: PolicyFormat, source: string) => JSON.stringify({ format, source });

export const policyAsCodeClient = {
  summary: () => request<PolicySummary>("/api/modules/policy-as-code/summary"),
  list: () => request<{ items: PolicyListItem[]; total: number }>("/api/modules/policy-as-code/policies"),
  get: (id: string) => request<PolicyRecord>(`/api/modules/policy-as-code/policies/${encodeURIComponent(id)}`),
  create: (format: PolicyFormat, source: string) => request<PolicyRecord>("/api/modules/policy-as-code/policies", { method: "POST", body: sourceBody(format, source) }),
  update: (id: string, format: PolicyFormat, source: string) => request<PolicyRecord>(`/api/modules/policy-as-code/policies/${encodeURIComponent(id)}`, { method: "PUT", body: sourceBody(format, source) }),
  remove: (id: string) => request<{ deleted: string }>(`/api/modules/policy-as-code/policies/${encodeURIComponent(id)}`, { method: "DELETE" }),
  validate: (format: PolicyFormat, source: string) => request<PolicyValidation>("/api/modules/policy-as-code/validate", { method: "POST", body: sourceBody(format, source) }),
  evaluateSource: (format: PolicyFormat, source: string, facts: Record<string, unknown>) => request<PolicyEvaluation>("/api/modules/policy-as-code/evaluate", { method: "POST", body: JSON.stringify({ format, source, facts }) }),
  evaluateEnabled: (facts: Record<string, unknown>) => request<PolicyEvaluation>("/api/modules/policy-as-code/evaluate", { method: "POST", body: JSON.stringify({ facts }) }),
};
