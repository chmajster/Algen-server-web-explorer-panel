import { apiAt, request } from "../../../core/api/transport";
import type { DnsConfiguration, DnsTestResult, NetworkChange, NetworkConnectivityResult, NetworkManagementState, NetworkOverview, NetworkPlan, NetworkPolicy, NetworkTransaction, ProxmoxSafety, RoutingSnapshot } from "../../../core/api/contracts";

export const networkClient = {
  proxmoxSafety: () => request<ProxmoxSafety>("/api/admin/system/proxmox-safety"),
  networkOverview: () => request<NetworkOverview>("/api/admin/network/overview"),
  networkDns: () => request<DnsConfiguration>("/api/admin/network/dns"),
  testNetworkDns: (hostname: string) => request<DnsTestResult>("/api/admin/network/dns/test", { method: "POST", body: JSON.stringify({ hostname }) }),
  networkRouting: () => request<RoutingSnapshot>("/api/admin/network/routing"),
  networkManagement: () => request<NetworkManagementState>("/api/admin/network/management"),
  testNetworkConnectivity: (kind: "ping" | "trace" | "tcp", target: string, port?: number | null) => request<NetworkConnectivityResult>("/api/admin/network/connectivity/test", { method: "POST", body: JSON.stringify({ kind, target, port: port || null }) }),
  planNetworkChange: (change: NetworkChange) => request<NetworkPlan>("/api/admin/network/plans", { method: "POST", body: JSON.stringify({ change }) }),
  networkPolicy: () => request<NetworkPolicy>("/api/admin/network/policy"),
  saveNetworkPolicy: (change_confirmation_timeout_seconds: number) => request<NetworkPolicy>("/api/admin/network/policy", { method: "PUT", body: JSON.stringify({ change_confirmation_timeout_seconds, confirm: true }) }),
  resetNetworkPolicy: () => request<NetworkPolicy>("/api/admin/network/policy/reset", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  applyNetworkPlan: (plan_id: string, confirmation_phrase = "") => request<NetworkTransaction>("/api/admin/network/apply", { method: "POST", body: JSON.stringify({ plan_id, confirmation_phrase }) }),
  activeNetworkTransaction: (baseUrl = "", signal?: AbortSignal) => request<NetworkTransaction | null>(apiAt(baseUrl, "/api/admin/network/transactions/active"), { signal }),
  networkTransactionStatus: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/status`), { signal }),
  confirmNetworkTransaction: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => baseUrl
    ? request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/confirm`), { method: "POST", signal })
    : request<NetworkTransaction>("/api/admin/network/confirm", { method: "POST", body: JSON.stringify({ transaction_id }), signal }),
  rollbackNetworkTransaction: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => baseUrl
    ? request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/rollback`), { method: "POST", signal })
    : request<NetworkTransaction>("/api/admin/network/rollback", { method: "POST", body: JSON.stringify({ transaction_id }), signal })
} as const;
