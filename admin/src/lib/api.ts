export const getToken = () => localStorage.getItem("admin_token");
export const setToken = (token: string) => localStorage.setItem("admin_token", token);
export const clearToken = () => localStorage.removeItem("admin_token");

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function fetchWithToken(endpoint: string, options: RequestInit = {}) {
  const token = getToken();
  
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };

  // Only inject admin token for /admin endpoints
  if (endpoint.includes("/admin/") && token) {
    headers["X-Admin-Token"] = token;
  }

  let baseUrl = import.meta.env.VITE_API_URL || '/api/v1';
  if (baseUrl.startsWith('http') && !baseUrl.endsWith('/v1')) {
    baseUrl = baseUrl.replace(/\/$/, '') + '/v1';
  }

  const response = await fetch(`${baseUrl}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new ApiError(`Request failed: ${response.statusText}`, response.status);
  }

  return response.json();
}

// API methods
export const api = {
  // Dashboard
  getStats: () => fetchWithToken("/admin/dashboard/stats"),
  
  // Territories (using existing public endpoints)
  getTerritories: () => fetchWithToken("/territories"),
  getTerritoryState: () => fetchWithToken("/territories/state"),
  getTerritoryDetails: (id: string) => fetchWithToken(`/territories/${id}`),
  
  // Admin entities
  getPlayers: (offset = 0, limit = 50) => fetchWithToken(`/admin/dashboard/players?offset=${offset}&limit=${limit}`),
  getRuns: (offset = 0, limit = 50) => fetchWithToken(`/admin/dashboard/runs?offset=${offset}&limit=${limit}`),
  getRunDetails: (id: string) => fetchWithToken(`/runs/${id}`),
  getAuditEvents: (offset = 0, limit = 50) => fetchWithToken(`/admin/dashboard/audit-events?offset=${offset}&limit=${limit}`),
};
