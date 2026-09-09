import { request } from "../../../core/api/transport";

export type ApiContractStatus = "ok" | "warning" | "error";

export type ApiEndpoint = {
  path: string;
  method: string;
  tags: string[];
  summary: string;
  description: string;
  operation_id: string;
  deprecated: boolean;
  mutating: boolean;
  request_body_required: boolean;
  parameter_count: number;
  response_codes: string[];
};

export type ApiEndpointPage = {
  items: ApiEndpoint[];
  total: number;
  offset: number;
  limit: number;
};

export type ApiSummary = {
  status: ApiContractStatus;
  title: string;
  version: string;
  openapi: string;
  path_count: number;
  endpoint_count: number;
  read_only_count: number;
  mutating_count: number;
  deprecated_count: number;
  method_counts: Record<string, number>;
  tag_counts: Record<string, number>;
  issue_count: number;
  error_count: number;
  warning_count: number;
};

export type ApiContractIssue = {
  severity: "warning" | "error";
  code: string;
  path: string;
  method: string;
  message: string;
};

export type ApiContractReport = {
  summary: ApiSummary;
  issues: ApiContractIssue[];
};

export type ApiTestResult = {
  check: string;
  status: "passed" | "failed";
  severity: "warning" | "error";
  path: string;
  method: string;
  message: string;
};

export type ApiTestSummary = {
  status: ApiContractStatus;
  total: number;
  passed: number;
  failed: number;
  error_count: number;
  warning_count: number;
  score: number;
};

export type ApiTestReport = {
  summary: ApiTestSummary;
  results: ApiTestResult[];
};

export type ApiEndpointQuery = {
  search?: string;
  method?: string;
  tag?: string;
  includeDeprecated?: boolean;
  offset?: number;
  limit?: number;
};

function endpointQuery(query: ApiEndpointQuery): string {
  const params = new URLSearchParams();
  if (query.search?.trim()) params.set("search", query.search.trim());
  if (query.method?.trim()) params.set("method", query.method.trim());
  if (query.tag?.trim()) params.set("tag", query.tag.trim());
  if (query.includeDeprecated !== undefined) params.set("include_deprecated", String(query.includeDeprecated));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  const suffix = params.toString();
  return suffix ? `?${suffix}` : "";
}

export const apiExplorerClient = {
  summary: () => request<ApiSummary>("/api/modules/api/summary"),
  endpoints: (query: ApiEndpointQuery = {}) => request<ApiEndpointPage>(`/api/modules/api/endpoints${endpointQuery(query)}`),
  contract: () => request<ApiContractReport>("/api/modules/api/contract"),
  tests: () => request<ApiTestReport>("/api/modules/api/tests"),
};
