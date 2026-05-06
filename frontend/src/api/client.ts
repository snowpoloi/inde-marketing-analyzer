export type IntegrationSetting = {
  provider: string;
  display_name: string;
  is_enabled: boolean;
  config: Record<string, unknown>;
};

export type SyncRun = {
  id: string;
  provider: string;
  sync_type: string;
  status: string;
  date_from: string | null;
  date_to: string | null;
  started_at: string;
  finished_at: string | null;
  records_processed: number;
  error_message: string | null;
  meta: Record<string, unknown>;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

let authToken = localStorage.getItem("inde_token") ?? "";

export function setToken(token: string) {
  authToken = token;
  localStorage.setItem("inde_token", token);
}

export function clearToken() {
  authToken = "";
  localStorage.removeItem("inde_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password })
    }),
  me: () => request<{ id: string; email: string; is_admin: boolean }>("/auth/me"),
  dashboard: (section: string, dateFrom: string, dateTo: string) =>
    request<{ data: any }>(`/dashboard/${section}?date_from=${dateFrom}&date_to=${dateTo}`),
  integrations: () => request<IntegrationSetting[]>("/settings/integrations"),
  saveIntegration: (provider: string, payload: Pick<IntegrationSetting, "is_enabled" | "config">) =>
    request<IntegrationSetting>(`/settings/integrations/${provider}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  syncRuns: () => request<SyncRun[]>("/sync/runs"),
  triggerSync: (providers: string[], dateFrom: string, dateTo: string) =>
    request<SyncRun[]>("/sync/run", {
      method: "POST",
      body: JSON.stringify({ providers, date_from: dateFrom, date_to: dateTo })
    }),
  importCsv: (kind: "google" | "meta", reportDate: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const path =
      kind === "google"
        ? `/sync/import/google-ads-csv?report_date=${reportDate}`
        : `/sync/import/meta-ads-csv?fallback_date=${reportDate}`;
    return request<SyncRun>(path, { method: "POST", body });
  }
};

