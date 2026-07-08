export type FileItem = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  owner: string;
  group: string;
  mode: string;
  permissions: string;
  modified: number;
  mime: string;
};

export type Task = {
  id: string;
  type: string;
  op: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  source_paths: string[];
  destination_path: string;
  started_at: number | null;
  finished_at: number | null;
  bytes_transferred: number;
  total_bytes: number;
  progress_percent: number;
  progress: number;
  speed_bps: number;
  speed_human: string;
  eta_seconds: number | null;
  eta_human: string;
  current_file: string;
  files_done: number;
  files_total: number;
  rsync_exit_code: number | null;
  error_message: string;
  log_tail: string[];
  errors: string[];
};

export type SettingsMe = {
  username: string;
  uid: number;
  gid: number;
  groups: string[];
  home: string;
  shell: string;
  gecos: string;
  is_admin: boolean;
  language: "pl-PL" | "en-US";
  theme: "light" | "dark" | "system";
};

export type AdminUser = SettingsMe & { is_system: boolean };
export type AdminGroup = { name: string; gid: number; members: string[] };
export type SystemStatus = { service: string; version: string; port: number; data_dir: string; log_dir: string; temp_dir: string };

let csrfToken = localStorage.getItem("webnas_csrf") || "";

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (csrfToken && options.method && options.method !== "GET") headers.set("x-csrf-token", csrfToken);
  const res = await fetch(url, { ...options, headers, credentials: "include" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  const data = await request<{ username: string; home: string; csrf_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
  csrfToken = data.csrf_token;
  localStorage.setItem("webnas_csrf", csrfToken);
  return data;
}

export async function me() {
  const data = await request<{ username: string; home: string; csrf_token: string }>("/api/auth/me");
  csrfToken = data.csrf_token;
  localStorage.setItem("webnas_csrf", csrfToken);
  return data;
}

export function logout() {
  return request("/api/auth/logout", { method: "POST", body: "{}" }).finally(() => {
    csrfToken = "";
    localStorage.removeItem("webnas_csrf");
  });
}

export const api = {
  list: (path?: string) => request<{ path: string; items: FileItem[] }>(`/api/files/list?path=${encodeURIComponent(path || "")}`),
  mkdir: (path: string) => request("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path }) }),
  create: (path: string) => request("/api/files/create", { method: "POST", body: JSON.stringify({ path }) }),
  copy: (src: string | string[], dst: string) => request<{ task_id: string }>("/api/files/copy", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst } : { src, dst }) }),
  move: (src: string | string[], dst: string) => request<{ task_id: string }>("/api/files/move", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst } : { src, dst }) }),
  rename: (src: string, dst: string) => request("/api/files/rename", { method: "POST", body: JSON.stringify({ src, dst }) }),
  delete: (path: string) => request<{ task_id: string }>("/api/files/delete", { method: "POST", body: JSON.stringify({ path }) }),
  trash: (path: string) => request("/api/files/trash", { method: "POST", body: JSON.stringify({ path }) }),
  preview: (path: string) => request<{ path: string; mime: string; content_base64: string }>(`/api/files/preview?path=${encodeURIComponent(path)}`),
  stat: (path: string) => request<FileItem>(`/api/files/stat?path=${encodeURIComponent(path)}`),
  search: (path: string, query: string) => request<{ items: FileItem[] }>(`/api/files/search?path=${encodeURIComponent(path)}&query=${encodeURIComponent(query)}`),
  tasks: () => request<Task[]>("/api/files/tasks"),
  task: (taskId: string) => request<Task>(`/api/files/tasks/${encodeURIComponent(taskId)}`),
  cancelTask: (taskId: string) => request("/api/files/tasks/" + encodeURIComponent(taskId) + "/cancel", { method: "POST", body: "{}" }),
  upload: (path: string, file: File) => {
    const body = new FormData();
    body.set("path", path);
    body.set("file", file);
    return request("/api/files/upload", { method: "POST", body });
  },
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: Partial<Pick<SettingsMe, "language" | "theme">>) => request("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  createUser: (payload: Record<string, unknown>) => request<AdminUser>("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  patchUser: (username: string, payload: Record<string, unknown>) => request<AdminUser>(`/api/admin/users/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ admin_password, confirm: true }) }),
  lockUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}/lock`, { method: "POST", body: JSON.stringify({ admin_password }) }),
  unlockUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}/unlock`, { method: "POST", body: JSON.stringify({ admin_password }) }),
  changeUserPassword: (username: string, payload: Record<string, unknown>) => request(`/api/admin/users/${encodeURIComponent(username)}/change-password`, { method: "POST", body: JSON.stringify(payload) }),
  adminGroups: () => request<AdminGroup[]>("/api/admin/groups"),
  createGroup: (payload: Record<string, unknown>) => request("/api/admin/groups", { method: "POST", body: JSON.stringify(payload) }),
  deleteGroup: (groupname: string, admin_password: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}`, { method: "DELETE", body: JSON.stringify({ admin_password, confirm: true }) }),
  addGroupMember: (groupname: string, payload: Record<string, unknown>) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members`, { method: "POST", body: JSON.stringify(payload) }),
  removeGroupMember: (groupname: string, username: string, admin_password: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ admin_password }) }),
  chown: (payload: Record<string, unknown>) => request("/api/admin/files/ownership", { method: "POST", body: JSON.stringify(payload) }),
  chmod: (path: string, mode: string) => request("/api/files/chmod", { method: "POST", body: JSON.stringify({ path, mode }) }),
  systemStatus: () => request<SystemStatus>("/api/admin/system/status"),
  restartSystem: (admin_password: string) => request("/api/admin/system/restart", { method: "POST", body: JSON.stringify({ admin_password }) })
};

export function downloadUrl(path: string) {
  return `/api/files/download?path=${encodeURIComponent(path)}`;
}
