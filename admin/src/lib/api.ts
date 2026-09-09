export const API_BASE_URL = (
  import.meta.env.VITE_API_URL || "https://run-backend-ngyo.onrender.com"
)
  .replace(/\/+$/, "")
  .replace(/\/v1$/, "");
export const getToken = () => sessionStorage.getItem("admin_token");
export const setToken = (token: string) => {
  localStorage.removeItem("admin_token");
  sessionStorage.setItem("admin_token", token);
};
export const clearToken = () => {
  sessionStorage.removeItem("admin_token");
  localStorage.removeItem("admin_token");
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function request<T = any>(
  endpoint: string,
  options: RequestInit = {},
  token = getToken(),
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180000);
  try {
    const headers = new Headers(options.headers);
    headers.set("Content-Type", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${API_BASE_URL}/v1${endpoint}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const detail =
        typeof body?.detail === "string"
          ? body.detail
          : `Request failed (${response.status})`;
      if (
        response.status === 401 &&
        token &&
        !endpoint.startsWith("/auth/profile")
      ) {
        clearToken();
        window.dispatchEvent(new Event("storage"));
      }
      throw new ApiError(detail, response.status);
    }
    return response.status === 204 ? (null as T) : await response.json();
  } catch (error) {
    if (controller.signal.aborted)
      throw new Error(
        "The server took too long to respond. It may be waking up. Retry shortly.",
      );
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
const post = (path: string, body: unknown) =>
  request(path, { method: "POST", body: JSON.stringify(body) });
export const api = {
  login: (username: string, password: string) =>
    request(
      "/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ username, password, scope: "admin" }),
      },
      null,
    ),
  logout: () => post("/auth/logout?scope=admin", {}),
  me: () => request("/admin/console/me"),
  members: () => request("/admin/console/members"),
  addMember: (body: unknown) => post("/admin/console/members", body),
  memberState: (id: string, active: boolean) =>
    request(`/admin/console/members/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ active }),
    }),
  credentials: () => request("/auth/profile?scope=admin"),
  updateCredentials: (body: object) =>
    request("/auth/profile", {
      method: "PUT",
      body: JSON.stringify({ ...body, scope: "admin" }),
    }),
  notes: () => request("/admin/console/notes"),
  addNote: (body: unknown) => post("/admin/console/notes", body),
  editNote: (id: string, body: unknown) =>
    request(`/admin/console/notes/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  assistant: (question: string, history: unknown[]) =>
    post("/admin/console/assistant", { question, history }),
  getStats: () => request("/admin/dashboard/stats"),
  getTerritories: () => request("/territories"),
  getTerritoryState: () => request("/territories/state"),
  getTerritoryDetails: (id: string) => request(`/territories/${id}`),
  getCapturedAreas: () =>
    request("/captured-areas?linked_only=true", {
      headers: { "X-Device-Id": "00000000-0000-4000-8000-000000000000" },
    }),
  getPlayers: (offset = 0, limit = 50) =>
    request(`/admin/dashboard/players?offset=${offset}&limit=${limit}`),
  getRuns: (offset = 0, limit = 50) =>
    request(`/admin/dashboard/runs?offset=${offset}&limit=${limit}`),
  getRunDetails: (id: string) => request(`/admin/dashboard/runs/${id}`),
  getAuditEvents: (offset = 0, limit = 50) =>
    request(`/admin/dashboard/audit-events?offset=${offset}&limit=${limit}`),
  getSystem: () => request("/admin/dashboard/system"),
  simulate: (body: unknown) => post("/admin/dashboard/simulate", body),
  reverseRun: (id: string, operator_ref: string, reason: string) =>
    post(`/admin/review/runs/${id}/reverse`, { operator_ref, reason }),
  rebuildTerritory: (id: string, operator_ref: string, reason: string) =>
    post(`/admin/dashboard/territories/${id}/rebuild`, {
      operator_ref,
      reason,
    }),
};
