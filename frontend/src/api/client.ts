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

export type BankTransactionMatch = {
  order_id: string;
  status: string | null;
  date_added: string;
  order_total: number;
  product_amount: number;
  shipping: number;
  matched_bank_total: number;
  amount_gap: number;
  payment_coverage: string;
  match_reason: string;
  related_transactions: Array<{
    id: string;
    transaction_date: string;
    bank_name: string;
    amount: number;
    description: string;
    reference: string | null;
  }>;
};

export type BankTransaction = {
  id: string;
  bank_name: string;
  account: string | null;
  transaction_date: string;
  value_date: string | null;
  description: string;
  counterparty: string | null;
  reference: string | null;
  amount: number;
  debit: number;
  credit: number;
  balance: number | null;
  currency: string;
  category: string;
  transaction_type: string;
  source_filename: string;
  match: BankTransactionMatch | null;
  review_reason: string | null;
};

export type BankDashboard = {
  summary: {
    deposits: number;
    expenses: number;
    net_cashflow: number;
    bank_fees: number;
    transactions: number;
    unmatched_deposits: number;
  };
  expense_categories: Array<{
    category: string;
    transactions: number;
    amount: number;
  }>;
  deposits: BankTransaction[];
  transactions: BankTransaction[];
};

export type OrderPayment = {
  id: string;
  transaction_date: string;
  bank_name: string;
  amount: number;
  description: string;
  reference: string | null;
  coverage: string;
  match_reason: string;
};

export type OrderRow = {
  order_id: string;
  date_added: string;
  order_status: string | null;
  payment_method: string | null;
  shipping_method: string | null;
  products_total: number;
  shipping_total: number;
  tax_total: number;
  order_total: number;
  paid_amount: number;
  balance_due: number;
  payment_status: string;
  product_quantity: number;
  product_lines: number;
  payments: OrderPayment[];
};

export type SupplierSale = {
  supplier: string;
  orders: number;
  product_lines: number;
  quantity: number;
  revenue: number;
};

export type SupplierProductSale = {
  supplier: string;
  sku: string | null;
  model: string | null;
  product_id: string | null;
  product_name: string;
  orders: number;
  quantity: number;
  revenue: number;
};

export type OrdersOverview = {
  summary: {
    orders: number;
    paid_orders: number;
    partial_orders: number;
    unpaid_orders: number;
    overpaid_orders: number;
    products_total: number;
    shipping_total: number;
    order_total: number;
    paid_amount: number;
    balance_due: number;
    product_quantity: number;
    suppliers: number;
  };
  orders: OrderRow[];
  supplier_sales: SupplierSale[];
  supplier_products: SupplierProductSale[];
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
  bankDashboard: (dateFrom: string, dateTo: string) =>
    request<{ data: BankDashboard }>(`/banks/transactions?date_from=${dateFrom}&date_to=${dateTo}`),
  ordersOverview: (dateFrom: string, dateTo: string) =>
    request<{ data: OrdersOverview }>(`/orders/overview?date_from=${dateFrom}&date_to=${dateTo}`),
  importBankFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ filename: string; total: number; imported: number; skipped: number }>("/banks/import", {
      method: "POST",
      body
    });
  },
  integrations: () => request<IntegrationSetting[]>("/settings/integrations"),
  opencartOrderStatuses: () => request<string[]>("/settings/opencart/order-statuses"),
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
