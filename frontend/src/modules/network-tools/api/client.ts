import { request } from "../../../core/api/transport";

export type DiagnosticResult = { success?: boolean; duration_ms?: number; output?: string; [key: string]: unknown };
const post = <T>(url: string, body: unknown) => request<T>(url, { method: "POST", body: JSON.stringify(body) });
export const networkToolsClient = {
  overview: () => request<Record<string, unknown>>("/api/modules/network-tools/overview"),
  ping: (target: string) => post<DiagnosticResult>("/api/modules/network-tools/ping", { target }),
  traceroute: (target: string) => post<DiagnosticResult>("/api/modules/network-tools/traceroute", { target }),
  dns: (hostname: string, record_type: string, server: string) => post<DiagnosticResult>("/api/modules/network-tools/dns", { hostname, record_type, server }),
  reverseDns: (address: string) => post<DiagnosticResult>("/api/modules/network-tools/reverse-dns", { address }),
  portTest: (target: string, port: number) => post<DiagnosticResult>("/api/modules/network-tools/port-test", { target, port }),
  httpTest: (url: string) => post<DiagnosticResult>("/api/modules/network-tools/http-test", { url }),
  routeLookup: (target: string) => post<DiagnosticResult>("/api/modules/network-tools/route-lookup", { target }),
  routes: () => request<Record<string, unknown>>("/api/modules/network-tools/routes"),
  connections: () => request<Record<string, unknown>>("/api/modules/network-tools/connections"),
};
