import { AlertTriangle, Braces, CheckCircle2, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { Translate } from "../../app/types";
import {
  apiExplorerClient,
  type ApiContractReport,
  type ApiEndpoint,
  type ApiTestReport,
} from "../../modules/api/api/client";
import "../../styles/api-explorer.css";

const METHODS = ["", "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"];

function statusTone(status: "ok" | "warning" | "error") {
  if (status === "ok") return "success";
  if (status === "error") return "danger";
  return "warning";
}

function methodTone(method: string) {
  return method === "GET" || method === "HEAD" || method === "OPTIONS" ? "read" : "write";
}

export function ApiExplorerApp({ t }: { t: Translate }) {
  const [report, setReport] = useState<ApiContractReport | null>(null);
  const [testReport, setTestReport] = useState<ApiTestReport | null>(null);
  const [endpoints, setEndpoints] = useState<ApiEndpoint[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [method, setMethod] = useState("");
  const [tag, setTag] = useState("");
  const [includeDeprecated, setIncludeDeprecated] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [contract, tests, page] = await Promise.all([
        apiExplorerClient.contract(),
        apiExplorerClient.tests(),
        apiExplorerClient.endpoints({ search, method, tag, includeDeprecated, limit: 500 }),
      ]);
      setReport(contract);
      setTestReport(tests);
      setEndpoints(page.items);
      setTotal(page.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      setLoading(false);
    }
  }, [includeDeprecated, method, search, t, tag]);

  useEffect(() => { void refresh(); }, [refresh]);

  const tags = useMemo(
    () => Object.keys(report?.summary.tag_counts || {}).sort((left, right) => left.localeCompare(right)),
    [report?.summary.tag_counts],
  );

  const failedTests = useMemo(
    () => testReport?.results.filter((result) => result.status === "failed") || [],
    [testReport],
  );

  const summary = report?.summary;
  const testSummary = testReport?.summary;

  return <section className="api-explorer-app">
    <header className="wn-page-header">
      <div className="wn-page-header-copy">
        <span className="wn-page-eyebrow">Development</span>
        <h2><Braces aria-hidden="true" /> API Explorer</h2>
        <p>Read-only inventory, diagnostics and structural test suite for the FastAPI OpenAPI contract exposed by WebNAS.</p>
      </div>
      <div className="wn-page-header-actions">
        {testSummary && <span className={`wn-status-badge tone-${statusTone(testSummary.status)}`}>Tests: {testSummary.score}%</span>}
        {summary && <span className={`wn-status-badge tone-${statusTone(summary.status)}`}>Contract: {summary.status}</span>}
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />
          <span>{t("action.refresh")}</span>
        </button>
      </div>
    </header>

    <div className="wn-page-section">
      <div className="wn-inline-alert tone-info api-explorer-notice">
        This module does not execute API requests. Contract tests inspect OpenAPI in memory only, preventing destructive calls and SSRF-style proxy behavior.
      </div>

      {error && <div className="wn-inline-alert tone-danger" role="alert">{error}</div>}

      {summary && <div className="api-explorer-stats" aria-label="API contract summary">
        <article className="wn-card wn-stat-card"><span>Endpoints</span><strong>{summary.endpoint_count}</strong><small>{summary.path_count} paths</small></article>
        <article className="wn-card wn-stat-card"><span>Read-only</span><strong>{summary.read_only_count}</strong><small>GET / HEAD / OPTIONS</small></article>
        <article className="wn-card wn-stat-card"><span>Mutating</span><strong>{summary.mutating_count}</strong><small>POST / PUT / PATCH / DELETE</small></article>
        <article className="wn-card wn-stat-card"><span>Contract issues</span><strong>{summary.issue_count}</strong><small>{summary.error_count} errors · {summary.warning_count} warnings</small></article>
        <article className="wn-card wn-stat-card"><span>API tests</span><strong>{testSummary ? `${testSummary.score}%` : "—"}</strong><small>{testSummary ? `${testSummary.passed}/${testSummary.total} passed` : "Loading"}</small></article>
        <article className="wn-card wn-stat-card"><span>OpenAPI</span><strong>{summary.openapi || "—"}</strong><small>{summary.title} {summary.version}</small></article>
      </div>}

      <section className="wn-card api-explorer-contract" aria-labelledby="api-test-suite">
        <div className="wn-section-header">
          <div>
            <h3 id="api-test-suite">API test suite</h3>
            <p>Runs read-only OpenAPI checks for metadata, paths, parameters, request bodies, responses, documentation and operation identifiers.</p>
          </div>
          {testSummary && <span className={`wn-status-badge tone-${statusTone(testSummary.status)}`}>
            {testSummary.passed}/{testSummary.total} passed
          </span>}
        </div>
        {!testReport && loading && <div className="wn-state wn-loading-state is-compact"><span className="wn-spinner" aria-hidden="true" />{t("status.loading")}</div>}
        {testReport && failedTests.length === 0 && <div className="wn-inline-alert tone-success api-explorer-health"><CheckCircle2 aria-hidden="true" />All API contract tests passed.</div>}
        {testReport && failedTests.length > 0 && <div className="api-explorer-issues">
          {failedTests.map((result, index) => <div className={`wn-inline-alert tone-${result.severity === "error" ? "danger" : "warning"}`} key={`${result.check}:${result.path}:${result.method}:${index}`}>
            <AlertTriangle aria-hidden="true" />
            <div><strong>{result.check}</strong><span>{result.method} {result.path}</span><p>{result.message}</p></div>
          </div>)}
        </div>}
      </section>

      <section className="wn-card api-explorer-contract" aria-labelledby="api-contract-health">
        <div className="wn-section-header">
          <div>
            <h3 id="api-contract-health">Contract validation</h3>
            <p>Checks duplicate operation IDs and common structural problems.</p>
          </div>
        </div>
        {!report && loading && <div className="wn-state wn-loading-state is-compact"><span className="wn-spinner" aria-hidden="true" />{t("status.loading")}</div>}
        {report && report.issues.length === 0 && <div className="wn-inline-alert tone-success api-explorer-health"><CheckCircle2 aria-hidden="true" />No contract issues detected.</div>}
        {report && report.issues.length > 0 && <div className="api-explorer-issues">
          {report.issues.map((issue, index) => <div className={`wn-inline-alert tone-${issue.severity === "error" ? "danger" : "warning"}`} key={`${issue.code}:${issue.path}:${issue.method}:${index}`}>
            <AlertTriangle aria-hidden="true" />
            <div><strong>{issue.code}</strong><span>{issue.method} {issue.path}</span><p>{issue.message}</p></div>
          </div>)}
        </div>}
      </section>

      <section aria-labelledby="api-endpoint-catalog">
        <div className="wn-section-header api-explorer-catalog-header">
          <div>
            <h3 id="api-endpoint-catalog">Endpoint catalog</h3>
            <p>{total} matching endpoints. The result is capped at 500 rows per request.</p>
          </div>
        </div>

        <div className="wn-filter-bar api-explorer-filters">
          <label className="wn-search-input">
            <Search aria-hidden="true" />
            <input aria-label="Search API endpoints" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Path, summary, tag or operation ID" />
          </label>
          <label className="wn-form-field">
            <span>Method</span>
            <select aria-label="HTTP method" value={method} onChange={(event) => setMethod(event.target.value)}>
              {METHODS.map((value) => <option key={value || "all"} value={value}>{value || "All methods"}</option>)}
            </select>
          </label>
          <label className="wn-form-field">
            <span>Tag</span>
            <select aria-label="OpenAPI tag" value={tag} onChange={(event) => setTag(event.target.value)}>
              <option value="">All tags</option>
              {tags.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="wn-checkbox api-explorer-deprecated">
            <input type="checkbox" checked={includeDeprecated} onChange={(event) => setIncludeDeprecated(event.target.checked)} />
            <span>Include deprecated</span>
          </label>
        </div>

        <div className="wn-data-table api-explorer-table">
          <div className="wn-table-scroll">
            <table>
              <thead><tr><th>Method</th><th>Path</th><th>Summary</th><th>Tags</th><th>Responses</th><th>Contract</th></tr></thead>
              <tbody>
                {endpoints.map((endpoint) => <tr key={`${endpoint.method}:${endpoint.path}`}>
                  <td><span className={`api-explorer-method ${methodTone(endpoint.method)}`}>{endpoint.method}</span></td>
                  <td><code className="api-explorer-path">{endpoint.path}</code><small>{endpoint.operation_id || "No operationId"}</small></td>
                  <td>{endpoint.summary || "—"}</td>
                  <td>{endpoint.tags.length ? endpoint.tags.join(", ") : "—"}</td>
                  <td><code>{endpoint.response_codes.join(", ") || "—"}</code></td>
                  <td><div className="api-explorer-flags">{endpoint.mutating && <span className="wn-status-badge tone-warning">mutating</span>}{endpoint.request_body_required && <span className="wn-status-badge tone-info">body</span>}{endpoint.deprecated && <span className="wn-status-badge tone-danger">deprecated</span>}</div></td>
                </tr>)}
                {!loading && endpoints.length === 0 && <tr><td colSpan={6}><div className="wn-state">No endpoints match the current filters.</div></td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </section>;
}
