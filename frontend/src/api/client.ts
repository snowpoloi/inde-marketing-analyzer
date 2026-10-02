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
    ignored_duplicates: number;
    ignored_duplicate_amount: number;
  };
  expense_categories: Array<{
    category: string;
    transactions: number;
    amount: number;
  }>;
  bank_totals: Array<{
    bank_name: string;
    account: string;
    transactions: number;
    credits: number;
    debits: number;
    net_cashflow: number;
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

export type OrderAnalyticsPeriodInput = {
  key: string;
  label: string;
  date_from: string;
  date_to: string;
};

export type OrderAnalyticsDefaults = {
  statuses: string[];
  aging_statuses: string[];
  processed_statuses: string[];
  completed_statuses: string[];
  cancelled_statuses: string[];
  group_by: "day" | "month";
  stale_days: number;
};

export type OrderAnalyticsOptions = {
  statuses: Array<{ name: string; orders: number }>;
  aging_statuses: string[];
  processed_statuses: string[];
  completed_statuses: string[];
  cancelled_statuses: string[];
  defaults: OrderAnalyticsDefaults;
};

export type OrderAnalyticsPoint = {
  bucket: string;
  orders: number;
  processed: number;
  completed: number;
  cancelled: number;
};

export type OrderStageTotals = {
  orders: number;
  customers: number;
  sub_total: number;
  shipping: number;
  coupon: number;
  taxes: number;
  total_value: number;
  average_order_value: number;
};

export type OrderAnalyticsPeriod = OrderAnalyticsPeriodInput & {
  orders: number;
  customers: number;
  processed: number;
  completed: number;
  cancelled: number;
  open: number;
  other_open: number;
  processed_rate: number;
  completion_rate: number;
  sub_total: number;
  shipping: number;
  coupon: number;
  taxes: number;
  total_value: number;
  average_order_value: number;
  stage_totals: {
    received: OrderStageTotals;
    processed: OrderStageTotals;
    completed: OrderStageTotals;
    cancelled: OrderStageTotals;
  };
  status_counts: Array<{ status: string; orders: number }>;
  series: OrderAnalyticsPoint[];
};

export type OrderStatusAging = {
  status: string;
  orders: number;
  stale_orders: number;
  average_days: number;
  max_days: number;
};

export type StaleOrder = {
  order_id: string;
  date_added: string;
  status: string;
  status_since: string;
  days_in_status: number;
  age_source: "tracked" | "estimated";
  total: number;
  payment_method: string | null;
  shipping_method: string | null;
};

export type OrderAnalytics = {
  summary: {
    orders: number;
    processed: number;
    completed: number;
    cancelled: number;
    open: number;
    other_open: number;
    processed_rate: number;
    completion_rate: number;
    stage_totals: OrderAnalyticsPeriod["stage_totals"];
    stale_orders: number;
    primary_period: string;
  };
  group_by: "day" | "month";
  stale_days: number;
  periods: OrderAnalyticsPeriod[];
  status_aging: OrderStatusAging[];
  stale_orders: StaleOrder[];
  stale_orders_total: number;
};

export type OrderAnalyticsRequest = {
  periods: OrderAnalyticsPeriodInput[];
  statuses: string[];
  aging_statuses: string[];
  processed_statuses: string[];
  completed_statuses: string[];
  cancelled_statuses: string[];
  group_by: "day" | "month";
  stale_days: number;
};

export type OrderAnalyticsDefaultsRequest = Omit<OrderAnalyticsRequest, "periods">;

export type SupplierSummary = {
  suppliers: number;
  purchases: number;
  freight: number;
  matched_products: number;
  unmatched_products: number;
  products_with_cogs: number;
};

export type SupplierProduct = {
  mapping_id: string;
  supplier_id: string;
  supplier: string;
  supplier_sku: string | null;
  supplier_code: string | null;
  supplier_ean: string | null;
  product_catalog_id: string | null;
  opencart_product_id: string | null;
  opencart_sku: string | null;
  opencart_model: string | null;
  product_name: string | null;
  current_cogs: number | null;
  previous_cogs: number | null;
  cost_change_percent: number | null;
  cost_source: string | null;
  cost_reference: string | null;
  cost_date: string | null;
  cost_confidence: number | null;
  match_status: string;
  match_method: string;
  match_confidence: number;
  verified: boolean;
  conversion_factor: number;
};

export type SupplierMatchCandidate = {
  product_catalog_id: string;
  product_id: string | null;
  sku: string | null;
  model: string | null;
  name: string;
  method: string;
  confidence: number;
};

export type UnmatchedSupplierProduct = {
  mapping_id: string;
  supplier: string;
  supplier_sku: string | null;
  supplier_code: string | null;
  supplier_ean: string | null;
  description: string | null;
  status: string;
  candidates: SupplierMatchCandidate[];
};

export type SupplierPerformance = {
  supplier_id: string;
  supplier: string;
  purchases: number;
  freight: number;
  freight_ratio: number;
  orders: number;
  average_order: number;
  average_freight_per_order: number;
  free_shipping_orders: number;
  paid_shipping_orders: number;
  unknown_shipping_orders: number;
  shipping_trend: Array<{ month: string; freight: number }>;
  shipping_by_type: Array<{ shipping_type: string; freight: number }>;
  free_shipping_threshold: number | null;
  threshold_gap: number;
  potential_freight_savings: number;
  price_increases: number;
  margin_erosion_products: Array<{
    mapping_id: string;
    product_name: string | null;
    supplier_sku: string | null;
    previous_cogs: number;
    current_cogs: number;
    increase_percent: number | null;
    current_price_net: number | null;
    margin_change_points: number | null;
  }>;
};

export type SupplierCostHistory = {
  id: string; date: string; source: string; reference: string | null;
  net_unit_cost: number; quantity: number; confidence: number; currency: string; status: string;
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
  orderAnalyticsOptions: () => request<{ data: OrderAnalyticsOptions }>("/orders/analytics/options"),
  orderAnalytics: (payload: OrderAnalyticsRequest) =>
    request<{ data: OrderAnalytics }>("/orders/analytics", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  saveOrderAnalyticsDefaults: (payload: OrderAnalyticsDefaultsRequest) =>
    request<{ data: OrderAnalyticsOptions }>("/orders/analytics/defaults", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  supplierSummary: (dateFrom: string, dateTo: string) =>
    request<{ data: SupplierSummary }>(`/suppliers/summary?date_from=${dateFrom}&date_to=${dateTo}`),
  supplierProducts: (asOf: string) =>
    request<{ data: { rows: SupplierProduct[] } }>(`/suppliers/products?as_of=${asOf}`),
  unmatchedSupplierProducts: () =>
    request<{ data: { rows: UnmatchedSupplierProduct[] } }>("/suppliers/unmatched"),
  supplierPerformance: (dateFrom: string, dateTo: string) =>
    request<{ data: { rows: SupplierPerformance[] } }>(
      `/suppliers/performance?date_from=${dateFrom}&date_to=${dateTo}`
    ),
  supplierCatalogSearch: (query: string) => request<{ data: { rows: SupplierMatchCandidate[] } }>(`/suppliers/catalog-search?q=${encodeURIComponent(query)}`),
  supplierCostHistory: (mappingId: string) => request<{ data: { rows: SupplierCostHistory[] } }>(`/suppliers/mappings/${mappingId}/cost-history`),
  saveSupplierThreshold: (supplierId: string, threshold: number | null) => request<{ data: { saved: boolean } }>(`/suppliers/${supplierId}/settings`, {
    method: "PUT", body: JSON.stringify({ free_shipping_threshold: threshold })
  }),
  supplierShippingSimulation: (supplierId: string, threshold: number, dateFrom: string, dateTo: string) =>
    request<{ data: { threshold: number; eligible_orders: number; orders: number; potential_savings: number; additional_purchase_to_threshold: number } }>(`/suppliers/${supplierId}/shipping-simulation?threshold=${threshold}&date_from=${dateFrom}&date_to=${dateTo}`),
  addManualSupplierCost: (payload: { supplier_id: string; supplier_product_map_id: string; purchase_date: string; net_unit_cost: number; source_reference: string }) =>
    request<{ data: { cost_id: string; duplicate: boolean } }>("/suppliers/costs/manual", { method: "POST", body: JSON.stringify(payload) }),
  verifySupplierMapping: (
    mappingId: string,
    payload: { product_catalog_id: string; conversion_factor: number; pack_quantity: number }
  ) =>
    request<{ data: { mapping_id: string; verified: boolean; costs_created: number } }>(
      `/suppliers/mappings/${mappingId}/verify`,
      { method: "PUT", body: JSON.stringify(payload) }
    ),
  importSupplierJson: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{
      data: {
        batch_id: string;
        duplicate: boolean;
        documents_imported: number;
        documents_skipped: number;
        product_lines: number;
        matched_lines: number;
        unmatched_lines: number;
        shipping_lines: number;
      };
    }>("/suppliers/imports/json", { method: "POST", body });
  },
  importBankFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ filename: string; total: number; imported: number; reconciled: number; removed_stale: number; skipped: number }>("/banks/import", {
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
  tiktokAuthorizationUrl: () => request<{ authorization_url: string }>("/settings/integrations/tiktok_ads/authorization-url"),
  completeTikTokAuthorization: (authCode: string, state: string) =>
    request<{ connected: boolean }>("/settings/integrations/tiktok_ads/authorization", {
      method: "POST",
      body: JSON.stringify({ auth_code: authCode, state })
    }),
  syncRuns: () => request<SyncRun[]>("/sync/runs"),
  triggerSync: (providers: string[], dateFrom: string, dateTo: string) =>
    request<SyncRun[]>("/sync/run", {
      method: "POST",
      body: JSON.stringify({ providers, date_from: dateFrom, date_to: dateTo })
    }),
  importCsv: (kind: "google" | "meta" | "tiktok", reportDate: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const path =
      kind === "google"
        ? `/sync/import/google-ads-csv?report_date=${reportDate}`
        : kind === "meta"
          ? `/sync/import/meta-ads-csv?fallback_date=${reportDate}`
          : `/sync/import/tiktok-ads-csv?fallback_date=${reportDate}`;
    return request<SyncRun>(path, { method: "POST", body });
  }
};
