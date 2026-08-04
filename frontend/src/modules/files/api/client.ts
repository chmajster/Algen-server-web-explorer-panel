import { request } from "../../../core/api/transport";
import type { FileItem, FileListResponse, TextFileResponse } from "../../../core/api/contracts";

export const filesClient = {
  list: (path?: string, params: Record<string, string | number | boolean | null | undefined> = {}) => {
    const query = new URLSearchParams({ path: path || "" });
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    });
    return request<FileListResponse>(`/api/files/list?${query.toString()}`);
  },
  tree: (path?: string) => request<{ path: string; items: FileItem[] }>(`/api/files/tree?path=${encodeURIComponent(path || "")}`),
  mkdir: (path: string) => request("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path }) }),
  create: (path: string) => request("/api/files/create", { method: "POST", body: JSON.stringify({ path }) }),
  copy: (src: string | string[], dst: string, priority = 0) => request<{ task_id: string }>("/api/files/copy", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst, priority } : { src, dst, priority }) }),
  move: (src: string | string[], dst: string, priority = 0) => request<{ task_id: string }>("/api/files/move", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst, priority } : { src, dst, priority }) }),
  rename: (src: string, dst: string) => request("/api/files/rename", { method: "POST", body: JSON.stringify({ src, dst }) }),
  delete: (path: string | string[]) => request<{ task_id: string; task_ids?: string[] }>("/api/files/delete", { method: "POST", body: JSON.stringify(Array.isArray(path) ? { paths: path } : { path }) }),
  trash: (path: string) => request("/api/files/trash", { method: "POST", body: JSON.stringify({ path }) }),
  preview: (path: string) => request<{ path: string; mime: string; content_base64: string }>(`/api/files/preview?path=${encodeURIComponent(path)}`),
  readText: (path: string) => request<TextFileResponse>(`/api/files/text?path=${encodeURIComponent(path)}`),
  writeText: (path: string, content: string, expected_mtime_ns: string) => request<Omit<TextFileResponse, "content"> & { ok: boolean }>("/api/files/text", {
    method: "PUT",
    body: JSON.stringify({ path, content, expected_mtime_ns }),
  }),
  stat: (path: string) => request<FileItem>(`/api/files/stat?path=${encodeURIComponent(path)}`),
  search: (path: string, query: string) => request<{ items: FileItem[] }>(`/api/files/search?path=${encodeURIComponent(path)}&query=${encodeURIComponent(query)}`),
  upload: (path: string, file: File) => {
    const body = new FormData();
    body.set("path", path);
    body.set("file", file);
    return request("/api/files/upload", { method: "POST", body });
  },
  startUpload: (path: string, file: File) => request<{ upload_id: string; offset: number; size: number; path: string; completed: boolean }>("/api/files/uploads", { method: "POST", body: JSON.stringify({ path, filename: file.name, size: file.size }) }),
  uploadChunk: (uploadId: string, offset: number, chunk: Blob, signal?: AbortSignal) => request<{ upload_id: string; offset: number; size: number; path: string; completed: boolean }>(`/api/files/uploads/${encodeURIComponent(uploadId)}`, { method: "PATCH", body: chunk, headers: { "Upload-Offset": String(offset) }, signal }),
  cancelUpload: (uploadId: string) => request(`/api/files/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE", body: "{}" })
} as const;

export function downloadUrl(path: string) {
  return `/api/files/download?path=${encodeURIComponent(path)}`;
}
