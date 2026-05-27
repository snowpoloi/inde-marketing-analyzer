import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Download,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  TrendingUp
} from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { aadeInvoiceTypeLabel, formatAadeInvoiceType } from "../utils/aadeInvoiceTypes";
import "../styles/date-presets.css";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

type DatePreset = {
  key: string;
  label: string;
  fromOffset: number;
  toOffset: number;
};

const datePresets: DatePreset[] = [
  { key: "today", label: "Today", fromOffset: 0, toOffset: 0 },
  { key: "yesterday", label: "Yesterday", fromOffset: -1, toOffset: -1 },
  { key: "last-7", label: "Last 7 days", fromOffset: -6, toOffset: 0 },
  { key: "last-30", label: "Last 30 days", fromOffset: -29, toOffset: 0 }
];

function presetRange(preset: DatePreset) {
  return {
    from: isoDate(preset.fromOffset),
    to: isoDate(preset.toOffset)
  };
}

type AuditAction = {
  area: string;
  title: string;
  severity: string;
  action: string;
  reason: string;
  metric: string;
  value: string | number;
};

type TrackingRow = {
  source: string;
  role: string;
  reported_orders: number;
  reported_revenue: number;
  opencart_orders: number;
  opencart_revenue: number;
  order_coverage_percent: number;
  revenue_coverage_percent: number;
  status: string;
  recommendation: string;
};

type CampaignAuditRow = {
  source?: string;
  source_label?: string;
  campaign_name: string;
  cost: number;
  conversions: number;
  conversion_value: number;
  roas: number;
  ctr: number;
  audit_action: string;
  severity: string;
  reason: string;
};

type ChannelAuditRow = {
  channel: string;
  source_medium: string;
  sessions: number;
  purchases: number;
  revenue: number;
  conversion_rate: number;
  revenue_per_session: number;
  audit_action: string;
  severity: string;
  reason: string;
};

type SearchConsoleAuditRow = {
  query: string | null;
  page: string | null;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
  audit_action: string;
  severity: string;
  reason: string;
};

type ProductAuditRow = {
  name: string;
  sku: string | null;
  model: string | null;
  product_id: string | null;
  quantity: number;
  orders: number;
  average_quantity_per_order: number;
  revenue: number;
  merchant_clicks: number;
  merchant_impressions: number;
  audit_action: string;
  severity: string;
  reason: string;
};

type FeedAuditRow = {
  item_id: string;
  title: string;
  clicks: number;
  impressions: number;
  ctr: number;
  availability: string | null;
  merchant_status: string | null;
  has_opencart_sales: boolean;
  audit_action: string;
  severity: string;
  reason: string;
};

type AadeSummary = {
  income_documents: number;
  expense_documents: number;
  cancelled_documents: number;
  income_gross: number;
  expense_gross: number;
  income_vat: number;
  expense_vat: number;
  opencart_orders: number;
  opencart_revenue: number;
  revenue_gap: number;
  revenue_gap_percent: number;
};

type AadeDocumentRow = {
  direction: string;
  invoice_type: string;
  documents: number;
  cancelled_documents: number;
  net_value: number;
  vat_amount: number;
  gross_value: number;
  audit_action: string;
  severity: string;
  reason: string;
};

type AadeSummaryMetric = {
  metric: string;
  value: string;
  detail: string;
};

type OperationRow = {
  label?: string;
  status?: string;
  orders: number;
  revenue: number;
  aov?: number;
  counts_as_sale?: boolean;
};

type ChangeRow = {
  field: string;
  changes: number;
  last_detected_at: string | null;
};

type SortDirection = "asc" | "desc";
type SortConfig = {
  key: string;
  direction: SortDirection;
};
type SortMap = Record<string, SortConfig>;
type SortAccessors<T> = Record<string, (row: T) => unknown>;
type ExportColumn<T> = {
  header: string;
  value: (row: T) => unknown;
};

type AuditData = {
  overview: {
    readiness_score: number;
    high_priority: number;
    medium_priority: number;
    positive_signals: number;
    actual_revenue: number;
    actual_orders: number;
    ad_spend: number;
    actual_roas: number;
  };
  priority_actions: AuditAction[];
  tracking: { rows: TrackingRow[] };
  campaigns: CampaignAuditRow[];
  channels: ChannelAuditRow[];
  search_console: SearchConsoleAuditRow[];
  products: ProductAuditRow[];
  feed: FeedAuditRow[];
  aade: {
    summary: AadeSummary;
    documents: AadeDocumentRow[];
    mismatches: AuditAction[];
  };
  operations: {
    statuses: OperationRow[];
    payments: OperationRow[];
    shipping: OperationRow[];
    customer_groups: OperationRow[];
    regions: OperationRow[];
    changes: ChangeRow[];
  };
};

const emptyAudit: AuditData = {
  overview: {
    readiness_score: 0,
    high_priority: 0,
    medium_priority: 0,
    positive_signals: 0,
    actual_revenue: 0,
    actual_orders: 0,
    ad_spend: 0,
    actual_roas: 0
  },
  priority_actions: [],
  tracking: { rows: [] },
  campaigns: [],
  channels: [],
  search_console: [],
  products: [],
  feed: [],
  aade: {
    summary: {
      income_documents: 0,
      expense_documents: 0,
      cancelled_documents: 0,
      income_gross: 0,
      expense_gross: 0,
      income_vat: 0,
      expense_vat: 0,
      opencart_orders: 0,
      opencart_revenue: 0,
      revenue_gap: 0,
      revenue_gap_percent: 0
    },
    documents: [],
    mismatches: []
  },
  operations: {
    statuses: [],
    payments: [],
    shipping: [],
    customer_groups: [],
    regions: [],
    changes: []
  }
};

function pct(value: number) {
  return `${number.format(value)}%`;
}

function metricId(row: ProductAuditRow) {
  return row.sku || row.model || row.product_id || "-";
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("el-GR", {
    dateStyle: "short",
    timeStyle: "short"
  }).format(new Date(value));
}

const initialAuditSorts: SortMap = {
  priority: { key: "severity", direction: "desc" },
  tracking: { key: "status", direction: "desc" },
  campaigns: { key: "roas", direction: "desc" },
  channels: { key: "revenue", direction: "desc" },
  "search-console": { key: "clicks", direction: "desc" },
  products: { key: "revenue", direction: "desc" },
  feed: { key: "clicks", direction: "desc" },
  "aade-findings": { key: "severity", direction: "desc" },
  "aade-documents": { key: "gross", direction: "desc" },
  "op-statuses": { key: "orders", direction: "desc" },
  "op-payments": { key: "orders", direction: "desc" },
  "op-shipping": { key: "orders", direction: "desc" },
  "op-regions": { key: "orders", direction: "desc" },
  "op-customer-groups": { key: "orders", direction: "desc" },
  "op-changes": { key: "last", direction: "desc" }
};

const severityRank: Record<string, number> = {
  critical: 6,
  high: 5,
  warning: 4,
  medium: 3,
  low: 2,
  positive: 1,
  success: 1,
  skipped: 0
};

const actionRank: Record<string, number> = {
  investigate_tracking: 6,
  "investigate tracking": 6,
  investigate_product_feed: 5,
  "investigate product/feed": 5,
  "investigate seo": 5,
  "investigate operations": 5,
  "investigate fiscal": 5,
  investigate: 5,
  "optimize seo": 4,
  pause: 4,
  reduce: 3,
  monitor: 2,
  protect: 1,
  scale: 1
};

function ranked(value: string | null | undefined, rankMap: Record<string, number>) {
  return rankMap[(value ?? "").toLowerCase()] ?? value ?? "";
}

function isEmptySortValue(value: unknown) {
  return value === null || value === undefined || value === "";
}

function compareSortValues(a: unknown, b: unknown) {
  if (isEmptySortValue(a) && isEmptySortValue(b)) {
    return 0;
  }
  if (isEmptySortValue(a)) {
    return 1;
  }
  if (isEmptySortValue(b)) {
    return -1;
  }
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  if (typeof a === "boolean" && typeof b === "boolean") {
    return Number(a) - Number(b);
  }
  return String(a).localeCompare(String(b), "el", { numeric: true, sensitivity: "base" });
}

function sortRows<T>(rows: T[], sort: SortConfig | undefined, accessors: SortAccessors<T>) {
  if (!sort || !accessors[sort.key]) {
    return rows;
  }
  return [...rows].sort((a, b) => {
    const result = compareSortValues(accessors[sort.key](a), accessors[sort.key](b));
    return sort.direction === "asc" ? result : -result;
  });
}

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : typeof value === "boolean" ? (value ? "Yes" : "No") : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function csvLine(values: unknown[]) {
  return values.map(csvCell).join(";");
}

function buildCsvSection<T>(title: string, rows: T[], columns: ExportColumn<T>[]) {
  return [
    csvLine([title]),
    csvLine(columns.map((column) => column.header)),
    ...rows.map((row) => csvLine(columns.map((column) => column.value(row))))
  ].join("\r\n");
}

function downloadCsv(filename: string, content: string) {
  const blob = new Blob([`\uFEFF${content}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const actionSorters: SortAccessors<AuditAction> = {
  area: (row) => row.area,
  severity: (row) => ranked(row.severity, severityRank),
  title: (row) => row.title,
  action: (row) => ranked(row.action, actionRank),
  reason: (row) => row.reason
};

const trackingSorters: SortAccessors<TrackingRow> = {
  source: (row) => row.source,
  role: (row) => row.role,
  orders: (row) => row.reported_orders,
  revenue: (row) => row.reported_revenue,
  orderCoverage: (row) => row.order_coverage_percent,
  revenueCoverage: (row) => row.revenue_coverage_percent,
  status: (row) => ranked(row.status, severityRank),
  recommendation: (row) => row.recommendation
};

const campaignSorters: SortAccessors<CampaignAuditRow> = {
  source: (row) => row.source_label ?? row.source ?? "",
  campaign: (row) => row.campaign_name,
  cost: (row) => row.cost,
  conv: (row) => row.conversions,
  value: (row) => row.conversion_value,
  roas: (row) => row.roas,
  ctr: (row) => row.ctr,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const channelSorters: SortAccessors<ChannelAuditRow> = {
  channel: (row) => row.channel,
  source: (row) => row.source_medium,
  sessions: (row) => row.sessions,
  purchases: (row) => row.purchases,
  revenue: (row) => row.revenue,
  cr: (row) => row.conversion_rate,
  rps: (row) => row.revenue_per_session,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const searchConsoleSorters: SortAccessors<SearchConsoleAuditRow> = {
  query: (row) => row.query ?? "",
  page: (row) => row.page ?? "",
  clicks: (row) => row.clicks,
  impressions: (row) => row.impressions,
  ctr: (row) => row.ctr,
  position: (row) => row.position,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const productSorters: SortAccessors<ProductAuditRow> = {
  product: (row) => row.name,
  sku: (row) => metricId(row),
  orders: (row) => row.orders,
  qty: (row) => row.quantity,
  qpo: (row) => row.average_quantity_per_order,
  revenue: (row) => row.revenue,
  merchant: (row) => row.merchant_clicks,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const feedSorters: SortAccessors<FeedAuditRow> = {
  title: (row) => row.title || row.item_id,
  item: (row) => row.item_id,
  clicks: (row) => row.clicks,
  impressions: (row) => row.impressions,
  ctr: (row) => row.ctr,
  availability: (row) => row.availability ?? "",
  status: (row) => row.merchant_status ?? "",
  sales: (row) => row.has_opencart_sales,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const aadeDocumentSorters: SortAccessors<AadeDocumentRow> = {
  direction: (row) => row.direction,
  invoice: (row) => formatAadeInvoiceType(row.invoice_type),
  documents: (row) => row.documents,
  cancelled: (row) => row.cancelled_documents,
  net: (row) => row.net_value,
  vat: (row) => row.vat_amount,
  gross: (row) => row.gross_value,
  action: (row) => ranked(row.audit_action, actionRank),
  reason: (row) => row.reason
};

const operationSorters: SortAccessors<OperationRow> = {
  label: (row) => row.label ?? row.status ?? "",
  orders: (row) => row.orders,
  revenue: (row) => row.revenue,
  aov: (row) => row.aov,
  sale: (row) => row.counts_as_sale
};

const changeSorters: SortAccessors<ChangeRow> = {
  field: (row) => row.field,
  changes: (row) => row.changes,
  last: (row) => (row.last_detected_at ? Date.parse(row.last_detected_at) : null)
};

export function AuditPage() {
  const today = isoDate();
  const [dateTo, setDateTo] = useState(today);
  const [dateFrom, setDateFrom] = useState(isoDate(-29));
  const [audit, setAudit] = useState<AuditData>(emptyAudit);
  const [sorts, setSorts] = useState<SortMap>(initialAuditSorts);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextDateFrom = dateFrom, nextDateTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const result = await api.dashboard("audit", nextDateFrom, nextDateTo);
      setAudit({ ...emptyAudit, ...result.data });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load audit");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function applyPreset(preset: DatePreset) {
    const range = presetRange(preset);
    setDateFrom(range.from);
    setDateTo(range.to);
    load(range.from, range.to);
  }

  const activePreset = datePresets.find((preset) => {
    const range = presetRange(preset);
    return range.from === dateFrom && range.to === dateTo;
  })?.key;

  function toggleSort(tableId: string, key: string) {
    setSorts((current) => {
      const active = current[tableId];
      return {
        ...current,
        [tableId]: {
          key,
          direction: active?.key === key && active.direction === "desc" ? "asc" : "desc"
        }
      };
    });
  }

  function sortDirection(tableId: string, key: string) {
    return sorts[tableId]?.key === key ? sorts[tableId].direction : null;
  }

  function sortable(tableId: string, key: string) {
    return {
      sortable: true,
      sortDirection: sortDirection(tableId, key),
      onSort: () => toggleSort(tableId, key)
    };
  }

  const sortedPriorityActions = useMemo(
    () => sortRows(audit.priority_actions, sorts.priority, actionSorters),
    [audit.priority_actions, sorts]
  );
  const sortedTrackingRows = useMemo(() => sortRows(audit.tracking.rows, sorts.tracking, trackingSorters), [audit.tracking.rows, sorts]);
  const sortedCampaigns = useMemo(() => sortRows(audit.campaigns, sorts.campaigns, campaignSorters), [audit.campaigns, sorts]);
  const sortedChannels = useMemo(() => sortRows(audit.channels, sorts.channels, channelSorters), [audit.channels, sorts]);
  const sortedSearchConsole = useMemo(
    () => sortRows(audit.search_console, sorts["search-console"], searchConsoleSorters),
    [audit.search_console, sorts]
  );
  const sortedProducts = useMemo(() => sortRows(audit.products, sorts.products, productSorters), [audit.products, sorts]);
  const sortedFeed = useMemo(() => sortRows(audit.feed, sorts.feed, feedSorters), [audit.feed, sorts]);
  const sortedAadeFindings = useMemo(
    () => sortRows(audit.aade.mismatches, sorts["aade-findings"], actionSorters),
    [audit.aade.mismatches, sorts]
  );
  const sortedAadeDocuments = useMemo(
    () => sortRows(audit.aade.documents, sorts["aade-documents"], aadeDocumentSorters),
    [audit.aade.documents, sorts]
  );
  const sortedStatuses = useMemo(
    () => sortRows(audit.operations.statuses, sorts["op-statuses"], operationSorters),
    [audit.operations.statuses, sorts]
  );
  const sortedPayments = useMemo(
    () => sortRows(audit.operations.payments, sorts["op-payments"], operationSorters),
    [audit.operations.payments, sorts]
  );
  const sortedShipping = useMemo(
    () => sortRows(audit.operations.shipping, sorts["op-shipping"], operationSorters),
    [audit.operations.shipping, sorts]
  );
  const sortedRegions = useMemo(
    () => sortRows(audit.operations.regions, sorts["op-regions"], operationSorters),
    [audit.operations.regions, sorts]
  );
  const sortedCustomerGroups = useMemo(
    () => sortRows(audit.operations.customer_groups, sorts["op-customer-groups"], operationSorters),
    [audit.operations.customer_groups, sorts]
  );
  const sortedChanges = useMemo(
    () => sortRows(audit.operations.changes, sorts["op-changes"], changeSorters),
    [audit.operations.changes, sorts]
  );

  const actionColumns: Column<AuditAction>[] = useMemo(
    () => [
      { key: "area", header: "Area", ...sortable("priority", "area"), render: (row) => row.area },
      { key: "severity", header: "Severity", ...sortable("priority", "severity"), render: (row) => <StatusBadge value={row.severity} /> },
      {
        key: "title",
        header: "Priority",
        ...sortable("priority", "title"),
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.title}</strong>
            <span>{row.metric}: {row.value}</span>
          </div>
        )
      },
      { key: "action", header: "Action", ...sortable("priority", "action"), render: (row) => <StatusBadge value={row.action} /> },
      { key: "reason", header: "Why it matters", ...sortable("priority", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const trackingColumns: Column<TrackingRow>[] = useMemo(
    () => [
      { key: "source", header: "Source", ...sortable("tracking", "source"), render: (row) => <strong>{row.source}</strong> },
      { key: "role", header: "Role", ...sortable("tracking", "role"), render: (row) => row.role },
      { key: "orders", header: "Orders", align: "right", ...sortable("tracking", "orders"), render: (row) => number.format(row.reported_orders) },
      { key: "revenue", header: "Revenue", align: "right", ...sortable("tracking", "revenue"), render: (row) => currency.format(row.reported_revenue) },
      { key: "orderCoverage", header: "Order coverage", align: "right", ...sortable("tracking", "orderCoverage"), render: (row) => pct(row.order_coverage_percent) },
      { key: "revenueCoverage", header: "Revenue coverage", align: "right", ...sortable("tracking", "revenueCoverage"), render: (row) => pct(row.revenue_coverage_percent) },
      { key: "status", header: "Status", ...sortable("tracking", "status"), render: (row) => <StatusBadge value={row.status} /> },
      { key: "recommendation", header: "Recommendation", ...sortable("tracking", "recommendation"), render: (row) => row.recommendation }
    ],
    [sorts]
  );

  const campaignColumns: Column<CampaignAuditRow>[] = useMemo(
    () => [
      { key: "source", header: "Source", ...sortable("campaigns", "source"), render: (row) => row.source_label ?? row.source ?? "-" },
      { key: "campaign", header: "Campaign", ...sortable("campaigns", "campaign"), render: (row) => <strong>{row.campaign_name}</strong> },
      { key: "cost", header: "Cost", align: "right", ...sortable("campaigns", "cost"), render: (row) => currency.format(row.cost) },
      { key: "conv", header: "Conv.", align: "right", ...sortable("campaigns", "conv"), render: (row) => number.format(row.conversions) },
      { key: "value", header: "Value", align: "right", ...sortable("campaigns", "value"), render: (row) => currency.format(row.conversion_value) },
      { key: "roas", header: "ROAS", align: "right", ...sortable("campaigns", "roas"), render: (row) => number.format(row.roas) },
      { key: "ctr", header: "CTR", align: "right", ...sortable("campaigns", "ctr"), render: (row) => pct(row.ctr) },
      { key: "action", header: "Action", ...sortable("campaigns", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("campaigns", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const channelColumns: Column<ChannelAuditRow>[] = useMemo(
    () => [
      { key: "channel", header: "Channel", ...sortable("channels", "channel"), render: (row) => <strong>{row.channel}</strong> },
      { key: "source", header: "Source / medium", ...sortable("channels", "source"), render: (row) => row.source_medium },
      { key: "sessions", header: "Sessions", align: "right", ...sortable("channels", "sessions"), render: (row) => number.format(row.sessions) },
      { key: "purchases", header: "Purchases", align: "right", ...sortable("channels", "purchases"), render: (row) => number.format(row.purchases) },
      { key: "revenue", header: "Revenue", align: "right", ...sortable("channels", "revenue"), render: (row) => currency.format(row.revenue) },
      { key: "cr", header: "CR", align: "right", ...sortable("channels", "cr"), render: (row) => pct(row.conversion_rate) },
      { key: "rps", header: "Rev/session", align: "right", ...sortable("channels", "rps"), render: (row) => currency.format(row.revenue_per_session) },
      { key: "action", header: "Action", ...sortable("channels", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("channels", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const searchConsoleColumns: Column<SearchConsoleAuditRow>[] = useMemo(
    () => [
      {
        key: "query",
        header: "Query",
        ...sortable("search-console", "query"),
        render: (row) => <strong>{row.query || "(not provided)"}</strong>
      },
      { key: "page", header: "Page", ...sortable("search-console", "page"), render: (row) => row.page || "-" },
      { key: "clicks", header: "Clicks", align: "right", ...sortable("search-console", "clicks"), render: (row) => number.format(row.clicks) },
      {
        key: "impressions",
        header: "Impressions",
        align: "right",
        ...sortable("search-console", "impressions"),
        render: (row) => number.format(row.impressions)
      },
      { key: "ctr", header: "CTR", align: "right", ...sortable("search-console", "ctr"), render: (row) => pct(row.ctr) },
      {
        key: "position",
        header: "Avg. position",
        align: "right",
        ...sortable("search-console", "position"),
        render: (row) => number.format(row.position)
      },
      { key: "action", header: "Action", ...sortable("search-console", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("search-console", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const productColumns: Column<ProductAuditRow>[] = useMemo(
    () => [
      { key: "product", header: "Product", ...sortable("products", "product"), render: (row) => <strong>{row.name}</strong> },
      { key: "sku", header: "SKU", ...sortable("products", "sku"), render: (row) => metricId(row) },
      { key: "orders", header: "Orders", align: "right", ...sortable("products", "orders"), render: (row) => number.format(row.orders) },
      { key: "qty", header: "Qty", align: "right", ...sortable("products", "qty"), render: (row) => number.format(row.quantity) },
      { key: "qpo", header: "Qty/order", align: "right", ...sortable("products", "qpo"), render: (row) => number.format(row.average_quantity_per_order) },
      { key: "revenue", header: "Revenue", align: "right", ...sortable("products", "revenue"), render: (row) => currency.format(row.revenue) },
      { key: "merchant", header: "Feed clicks", align: "right", ...sortable("products", "merchant"), render: (row) => number.format(row.merchant_clicks) },
      { key: "action", header: "Action", ...sortable("products", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("products", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const feedColumns: Column<FeedAuditRow>[] = useMemo(
    () => [
      { key: "title", header: "Feed item", ...sortable("feed", "title"), render: (row) => <strong>{row.title || row.item_id}</strong> },
      { key: "item", header: "Item ID", ...sortable("feed", "item"), render: (row) => row.item_id },
      { key: "clicks", header: "Clicks", align: "right", ...sortable("feed", "clicks"), render: (row) => number.format(row.clicks) },
      { key: "impressions", header: "Impressions", align: "right", ...sortable("feed", "impressions"), render: (row) => number.format(row.impressions) },
      { key: "ctr", header: "CTR", align: "right", ...sortable("feed", "ctr"), render: (row) => pct(row.ctr) },
      { key: "availability", header: "Availability", ...sortable("feed", "availability"), render: (row) => row.availability || "-" },
      { key: "status", header: "Status", ...sortable("feed", "status"), render: (row) => row.merchant_status || "-" },
      { key: "sales", header: "Sales match", ...sortable("feed", "sales"), render: (row) => (row.has_opencart_sales ? "Yes" : "No") },
      { key: "action", header: "Action", ...sortable("feed", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("feed", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const aadeSummaryRows = useMemo<AadeSummaryMetric[]>(
    () => [
      {
        metric: "Income documents",
        value: number.format(audit.aade.summary.income_documents),
        detail: `${currency.format(audit.aade.summary.income_gross)} gross, ${currency.format(audit.aade.summary.income_vat)} VAT`
      },
      {
        metric: "Expense documents",
        value: number.format(audit.aade.summary.expense_documents),
        detail: `${currency.format(audit.aade.summary.expense_gross)} gross, ${currency.format(audit.aade.summary.expense_vat)} VAT`
      },
      {
        metric: "Cancelled documents",
        value: number.format(audit.aade.summary.cancelled_documents),
        detail: "Marked cancelled in myDATA"
      },
      {
        metric: "OpenCart revenue",
        value: currency.format(audit.aade.summary.opencart_revenue),
        detail: `${number.format(audit.aade.summary.opencart_orders)} orders`
      },
      {
        metric: "Revenue gap",
        value: currency.format(audit.aade.summary.revenue_gap),
        detail: pct(audit.aade.summary.revenue_gap_percent)
      }
    ],
    [audit.aade.summary]
  );

  const aadeSummaryColumns: Column<AadeSummaryMetric>[] = useMemo(
    () => [
      { key: "metric", header: "Metric", render: (row) => <strong>{row.metric}</strong> },
      { key: "value", header: "Value", align: "right", render: (row) => row.value },
      { key: "detail", header: "Detail", render: (row) => row.detail }
    ],
    []
  );

  const aadeFindingColumns: Column<AuditAction>[] = useMemo(
    () => [
      { key: "severity", header: "Severity", ...sortable("aade-findings", "severity"), render: (row) => <StatusBadge value={row.severity} /> },
      {
        key: "title",
        header: "Finding",
        ...sortable("aade-findings", "title"),
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.title}</strong>
            <span>{row.metric}: {row.value}</span>
          </div>
        )
      },
      { key: "action", header: "Action", ...sortable("aade-findings", "action"), render: (row) => <StatusBadge value={row.action} /> },
      { key: "reason", header: "Reason", ...sortable("aade-findings", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  const aadeDocumentColumns: Column<AadeDocumentRow>[] = useMemo(
    () => [
      { key: "direction", header: "Direction", ...sortable("aade-documents", "direction"), render: (row) => <strong>{row.direction}</strong> },
      {
        key: "invoice",
        header: "Invoice type",
        ...sortable("aade-documents", "invoice"),
        render: (row) => {
          const label = aadeInvoiceTypeLabel(row.invoice_type);
          return (
            <div className="audit-title-cell">
              <strong>{row.invoice_type || "-"}</strong>
              {label ? <span>{label}</span> : null}
            </div>
          );
        }
      },
      { key: "documents", header: "Docs", align: "right", ...sortable("aade-documents", "documents"), render: (row) => number.format(row.documents) },
      {
        key: "cancelled",
        header: "Cancelled",
        align: "right",
        ...sortable("aade-documents", "cancelled"),
        render: (row) => number.format(row.cancelled_documents)
      },
      { key: "net", header: "Net", align: "right", ...sortable("aade-documents", "net"), render: (row) => currency.format(row.net_value) },
      { key: "vat", header: "VAT", align: "right", ...sortable("aade-documents", "vat"), render: (row) => currency.format(row.vat_amount) },
      { key: "gross", header: "Gross", align: "right", ...sortable("aade-documents", "gross"), render: (row) => currency.format(row.gross_value) },
      { key: "action", header: "Action", ...sortable("aade-documents", "action"), render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", ...sortable("aade-documents", "reason"), render: (row) => row.reason }
    ],
    [sorts]
  );

  function operationColumns(tableId: string): Column<OperationRow>[] {
    return [
      { key: "label", header: "Name", ...sortable(tableId, "label"), render: (row) => row.label ?? row.status ?? "-" },
      { key: "orders", header: "Orders", align: "right", ...sortable(tableId, "orders"), render: (row) => number.format(row.orders) },
      { key: "revenue", header: "Revenue", align: "right", ...sortable(tableId, "revenue"), render: (row) => currency.format(row.revenue) },
      { key: "aov", header: "AOV", align: "right", ...sortable(tableId, "aov"), render: (row) => (row.aov === undefined ? "-" : currency.format(row.aov)) },
      {
        key: "sale",
        header: "Counts",
        ...sortable(tableId, "sale"),
        render: (row) =>
          row.counts_as_sale === undefined ? "-" : <StatusBadge value={row.counts_as_sale ? "success" : "skipped"} />
      }
    ];
  }

  const changeColumns: Column<ChangeRow>[] = useMemo(
    () => [
      { key: "field", header: "Field", ...sortable("op-changes", "field"), render: (row) => row.field },
      { key: "changes", header: "Changes", align: "right", ...sortable("op-changes", "changes"), render: (row) => number.format(row.changes) },
      { key: "last", header: "Last detected", ...sortable("op-changes", "last"), render: (row) => formatDateTime(row.last_detected_at) }
    ],
    [sorts]
  );

  function exportAudit() {
    const overviewRows = [
      {
        score: `${number.format(audit.overview.readiness_score)}/100`,
        high_priority: audit.overview.high_priority,
        medium_priority: audit.overview.medium_priority,
        opportunities: audit.overview.positive_signals,
        actual_revenue: currency.format(audit.overview.actual_revenue),
        actual_orders: audit.overview.actual_orders,
        ad_spend: currency.format(audit.overview.ad_spend),
        actual_roas: number.format(audit.overview.actual_roas)
      }
    ];
    const sections = [
      [
        csvLine(["INDE Marketing Audit"]),
        csvLine(["Date from", dateFrom]),
        csvLine(["Date to", dateTo]),
        csvLine(["Exported at", formatDateTime(new Date().toISOString())])
      ].join("\r\n"),
      buildCsvSection("Overview", overviewRows, [
        { header: "Audit score", value: (row) => row.score },
        { header: "High priority", value: (row) => row.high_priority },
        { header: "Medium priority", value: (row) => row.medium_priority },
        { header: "Opportunities", value: (row) => row.opportunities },
        { header: "Actual revenue", value: (row) => row.actual_revenue },
        { header: "Actual orders", value: (row) => row.actual_orders },
        { header: "Ad spend", value: (row) => row.ad_spend },
        { header: "Actual ROAS", value: (row) => row.actual_roas }
      ]),
      buildCsvSection("What to check first", sortedPriorityActions, [
        { header: "Area", value: (row) => row.area },
        { header: "Severity", value: (row) => row.severity },
        { header: "Priority", value: (row) => row.title },
        { header: "Metric", value: (row) => row.metric },
        { header: "Value", value: (row) => row.value },
        { header: "Action", value: (row) => row.action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("Tracking health", sortedTrackingRows, [
        { header: "Source", value: (row) => row.source },
        { header: "Role", value: (row) => row.role },
        { header: "Orders", value: (row) => row.reported_orders },
        { header: "Revenue", value: (row) => currency.format(row.reported_revenue) },
        { header: "OpenCart orders", value: (row) => row.opencart_orders },
        { header: "OpenCart revenue", value: (row) => currency.format(row.opencart_revenue) },
        { header: "Order coverage", value: (row) => pct(row.order_coverage_percent) },
        { header: "Revenue coverage", value: (row) => pct(row.revenue_coverage_percent) },
        { header: "Status", value: (row) => row.status },
        { header: "Recommendation", value: (row) => row.recommendation }
      ]),
      buildCsvSection("Campaign audit", sortedCampaigns, [
        { header: "Source", value: (row) => row.source_label ?? row.source ?? "-" },
        { header: "Campaign", value: (row) => row.campaign_name },
        { header: "Cost", value: (row) => currency.format(row.cost) },
        { header: "Conversions", value: (row) => row.conversions },
        { header: "Value", value: (row) => currency.format(row.conversion_value) },
        { header: "ROAS", value: (row) => number.format(row.roas) },
        { header: "CTR", value: (row) => pct(row.ctr) },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("GA4 channel audit", sortedChannels, [
        { header: "Channel", value: (row) => row.channel },
        { header: "Source / medium", value: (row) => row.source_medium },
        { header: "Sessions", value: (row) => row.sessions },
        { header: "Purchases", value: (row) => row.purchases },
        { header: "Revenue", value: (row) => currency.format(row.revenue) },
        { header: "CR", value: (row) => pct(row.conversion_rate) },
        { header: "Revenue/session", value: (row) => currency.format(row.revenue_per_session) },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("Search Console SEO audit", sortedSearchConsole, [
        { header: "Query", value: (row) => row.query || "(not provided)" },
        { header: "Page", value: (row) => row.page || "-" },
        { header: "Clicks", value: (row) => row.clicks },
        { header: "Impressions", value: (row) => row.impressions },
        { header: "CTR", value: (row) => pct(row.ctr) },
        { header: "Average position", value: (row) => number.format(row.position) },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("Product opportunities", sortedProducts, [
        { header: "Product", value: (row) => row.name },
        { header: "SKU", value: (row) => metricId(row) },
        { header: "Orders", value: (row) => row.orders },
        { header: "Qty", value: (row) => row.quantity },
        { header: "Qty/order", value: (row) => number.format(row.average_quantity_per_order) },
        { header: "Revenue", value: (row) => currency.format(row.revenue) },
        { header: "Feed clicks", value: (row) => row.merchant_clicks },
        { header: "Feed impressions", value: (row) => row.merchant_impressions },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("Merchant feed audit", sortedFeed, [
        { header: "Feed item", value: (row) => row.title || row.item_id },
        { header: "Item ID", value: (row) => row.item_id },
        { header: "Clicks", value: (row) => row.clicks },
        { header: "Impressions", value: (row) => row.impressions },
        { header: "CTR", value: (row) => pct(row.ctr) },
        { header: "Availability", value: (row) => row.availability || "-" },
        { header: "Status", value: (row) => row.merchant_status || "-" },
        { header: "Sales match", value: (row) => row.has_opencart_sales },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("AADE fiscal summary", aadeSummaryRows, [
        { header: "Metric", value: (row) => row.metric },
        { header: "Value", value: (row) => row.value },
        { header: "Detail", value: (row) => row.detail }
      ]),
      buildCsvSection("AADE fiscal findings", sortedAadeFindings, [
        { header: "Severity", value: (row) => row.severity },
        { header: "Finding", value: (row) => row.title },
        { header: "Metric", value: (row) => row.metric },
        { header: "Value", value: (row) => row.value },
        { header: "Action", value: (row) => row.action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("AADE document groups", sortedAadeDocuments, [
        { header: "Direction", value: (row) => row.direction },
        { header: "Invoice type", value: (row) => formatAadeInvoiceType(row.invoice_type) },
        { header: "Documents", value: (row) => row.documents },
        { header: "Cancelled", value: (row) => row.cancelled_documents },
        { header: "Net", value: (row) => currency.format(row.net_value) },
        { header: "VAT", value: (row) => currency.format(row.vat_amount) },
        { header: "Gross", value: (row) => currency.format(row.gross_value) },
        { header: "Action", value: (row) => row.audit_action },
        { header: "Reason", value: (row) => row.reason }
      ]),
      buildCsvSection("OpenCart order statuses", sortedStatuses, operationExportColumns()),
      buildCsvSection("OpenCart payment methods", sortedPayments, operationExportColumns()),
      buildCsvSection("OpenCart shipping methods", sortedShipping, operationExportColumns()),
      buildCsvSection("OpenCart regions", sortedRegions, operationExportColumns()),
      buildCsvSection("OpenCart customer groups", sortedCustomerGroups, operationExportColumns()),
      buildCsvSection("OpenCart detected order changes", sortedChanges, [
        { header: "Field", value: (row) => row.field },
        { header: "Changes", value: (row) => row.changes },
        { header: "Last detected", value: (row) => formatDateTime(row.last_detected_at) }
      ])
    ];
    downloadCsv(`inde-marketing-audit-${dateFrom}-to-${dateTo}.csv`, sections.join("\r\n\r\n"));
  }

  function operationExportColumns(): ExportColumn<OperationRow>[] {
    return [
      { header: "Name", value: (row) => row.label ?? row.status ?? "-" },
      { header: "Orders", value: (row) => row.orders },
      { header: "Revenue", value: (row) => currency.format(row.revenue) },
      { header: "AOV", value: (row) => (row.aov === undefined ? "-" : currency.format(row.aov)) },
      { header: "Counts as sale", value: (row) => row.counts_as_sale }
    ];
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Marketing audit</h1>
          <p>Read-only checks across ads, analytics, feed, OpenCart orders and product demand.</p>
        </div>
        <div className="date-controls">
          <div className="preset-tabs" aria-label="Date presets">
            {datePresets.map((preset) => (
              <button
                className={`date-preset ${activePreset === preset.key ? "active" : ""}`}
                key={preset.key}
                onClick={() => applyPreset(preset)}
                disabled={loading}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <button className="secondary-action compact" onClick={exportAudit} disabled={loading}>
            <Download size={17} />
            Export CSV
          </button>
          <button className="primary-action compact" onClick={() => load()} disabled={loading}>
            <RefreshCw size={17} />
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="stats-grid">
        <StatCard label="Audit score" value={`${number.format(audit.overview.readiness_score)}/100`} detail="Higher means fewer urgent gaps" icon={ShieldCheck} />
        <StatCard label="High priority" value={number.format(audit.overview.high_priority)} detail="Critical or high findings" icon={AlertTriangle} />
        <StatCard label="Opportunities" value={number.format(audit.overview.positive_signals)} detail="Scale or strong signals" icon={CheckCircle2} />
        <StatCard label="Actual revenue" value={currency.format(audit.overview.actual_revenue)} detail={`${number.format(audit.overview.actual_orders)} OpenCart orders`} icon={TrendingUp} />
        <StatCard label="Actual ROAS" value={number.format(audit.overview.actual_roas)} detail={`${currency.format(audit.overview.ad_spend)} ad spend`} icon={Activity} />
      </section>

      <section className="panel audit-priority-panel">
        <div className="panel-title">
          <h2>What to check first</h2>
          <span>Highest impact issues and opportunities</span>
        </div>
        <DataTable rows={sortedPriorityActions} columns={actionColumns} empty="No priority findings for this period." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Tracking health</h2>
          <span>Attribution sources compared to OpenCart truth</span>
        </div>
        <DataTable rows={sortedTrackingRows} columns={trackingColumns} empty="No tracking data yet." />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>Campaign audit</h2>
            <span>Meta and Google Ads</span>
          </div>
          <DataTable rows={sortedCampaigns} columns={campaignColumns} empty="No campaign data yet." />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>GA4 channel audit</h2>
            <span>Traffic quality and revenue signals</span>
          </div>
          <DataTable rows={sortedChannels} columns={channelColumns} empty="No GA4 channel data yet." />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Search Console SEO audit</h2>
          <span>Organic queries, landing pages, CTR and position gaps</span>
        </div>
        <DataTable rows={sortedSearchConsole} columns={searchConsoleColumns} empty="No Search Console data yet." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Product opportunities</h2>
          <span>Distinct orders are treated as stronger demand than bulk quantity</span>
        </div>
        <DataTable rows={sortedProducts} columns={productColumns} empty="No product audit data yet." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Merchant feed audit</h2>
          <span>Products with visibility, clicks, sales match and feed risk</span>
        </div>
        <DataTable rows={sortedFeed} columns={feedColumns} empty="No Merchant Center data yet." />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>AADE fiscal summary</h2>
            <span>myDATA totals compared to OpenCart revenue</span>
          </div>
          <DataTable rows={aadeSummaryRows} columns={aadeSummaryColumns} empty="No AADE summary yet." />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>AADE fiscal findings</h2>
            <span>Revenue variance and cancellation checks</span>
          </div>
          <DataTable rows={sortedAadeFindings} columns={aadeFindingColumns} empty="No AADE findings for this period." />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>AADE document groups</h2>
          <span>Income and expense documents by invoice type</span>
        </div>
        <DataTable rows={sortedAadeDocuments} columns={aadeDocumentColumns} empty="No AADE documents yet." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>OpenCart operations audit</h2>
          <span>Status, payment, shipping and order changes</span>
        </div>
        <div className="operation-grid">
          <div>
            <h3>Order statuses</h3>
            <DataTable rows={sortedStatuses} columns={operationColumns("op-statuses")} empty="No statuses found." />
          </div>
          <div>
            <h3>Payment methods</h3>
            <DataTable rows={sortedPayments} columns={operationColumns("op-payments")} empty="No payment data found." />
          </div>
          <div>
            <h3>Shipping methods</h3>
            <DataTable rows={sortedShipping} columns={operationColumns("op-shipping")} empty="No shipping data found." />
          </div>
          <div>
            <h3>Regions</h3>
            <DataTable rows={sortedRegions} columns={operationColumns("op-regions")} empty="No region data found." />
          </div>
          <div>
            <h3>Customer groups</h3>
            <DataTable rows={sortedCustomerGroups} columns={operationColumns("op-customer-groups")} empty="No customer group data found." />
          </div>
          <div>
            <h3>Detected order changes</h3>
            <DataTable
              rows={sortedChanges}
              empty="No order changes detected in this period."
              columns={changeColumns}
            />
          </div>
        </div>
      </section>

      {loading ? (
        <div className="loading-overlay">
          <SearchCheck size={18} />
          Running audit
        </div>
      ) : null}
    </div>
  );
}
