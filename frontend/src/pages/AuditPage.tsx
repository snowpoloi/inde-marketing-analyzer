import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, SearchCheck, ShieldCheck, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
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
  products: ProductAuditRow[];
  feed: FeedAuditRow[];
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
  products: [],
  feed: [],
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

export function AuditPage() {
  const today = isoDate();
  const [dateTo, setDateTo] = useState(today);
  const [dateFrom, setDateFrom] = useState(isoDate(-29));
  const [audit, setAudit] = useState<AuditData>(emptyAudit);
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

  const actionColumns: Column<AuditAction>[] = useMemo(
    () => [
      { key: "area", header: "Area", render: (row) => row.area },
      { key: "severity", header: "Severity", render: (row) => <StatusBadge value={row.severity} /> },
      {
        key: "title",
        header: "Priority",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.title}</strong>
            <span>{row.metric}: {row.value}</span>
          </div>
        )
      },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.action} /> },
      { key: "reason", header: "Why it matters", render: (row) => row.reason }
    ],
    []
  );

  const trackingColumns: Column<TrackingRow>[] = useMemo(
    () => [
      { key: "source", header: "Source", render: (row) => <strong>{row.source}</strong> },
      { key: "role", header: "Role", render: (row) => row.role },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.reported_orders) },
      { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.reported_revenue) },
      { key: "orderCoverage", header: "Order coverage", align: "right", render: (row) => pct(row.order_coverage_percent) },
      { key: "revenueCoverage", header: "Revenue coverage", align: "right", render: (row) => pct(row.revenue_coverage_percent) },
      { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> },
      { key: "recommendation", header: "Recommendation", render: (row) => row.recommendation }
    ],
    []
  );

  const campaignColumns: Column<CampaignAuditRow>[] = useMemo(
    () => [
      { key: "source", header: "Source", render: (row) => row.source_label ?? row.source ?? "-" },
      { key: "campaign", header: "Campaign", render: (row) => <strong>{row.campaign_name}</strong> },
      { key: "cost", header: "Cost", align: "right", render: (row) => currency.format(row.cost) },
      { key: "conv", header: "Conv.", align: "right", render: (row) => number.format(row.conversions) },
      { key: "value", header: "Value", align: "right", render: (row) => currency.format(row.conversion_value) },
      { key: "roas", header: "ROAS", align: "right", render: (row) => number.format(row.roas) },
      { key: "ctr", header: "CTR", align: "right", render: (row) => pct(row.ctr) },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  const channelColumns: Column<ChannelAuditRow>[] = useMemo(
    () => [
      { key: "channel", header: "Channel", render: (row) => <strong>{row.channel}</strong> },
      { key: "source", header: "Source / medium", render: (row) => row.source_medium },
      { key: "sessions", header: "Sessions", align: "right", render: (row) => number.format(row.sessions) },
      { key: "purchases", header: "Purchases", align: "right", render: (row) => number.format(row.purchases) },
      { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) },
      { key: "cr", header: "CR", align: "right", render: (row) => pct(row.conversion_rate) },
      { key: "rps", header: "Rev/session", align: "right", render: (row) => currency.format(row.revenue_per_session) },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  const productColumns: Column<ProductAuditRow>[] = useMemo(
    () => [
      { key: "product", header: "Product", render: (row) => <strong>{row.name}</strong> },
      { key: "sku", header: "SKU", render: (row) => metricId(row) },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
      { key: "qpo", header: "Qty/order", align: "right", render: (row) => number.format(row.average_quantity_per_order) },
      { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) },
      { key: "merchant", header: "Feed clicks", align: "right", render: (row) => number.format(row.merchant_clicks) },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  const feedColumns: Column<FeedAuditRow>[] = useMemo(
    () => [
      { key: "title", header: "Feed item", render: (row) => <strong>{row.title || row.item_id}</strong> },
      { key: "item", header: "Item ID", render: (row) => row.item_id },
      { key: "clicks", header: "Clicks", align: "right", render: (row) => number.format(row.clicks) },
      { key: "impressions", header: "Impressions", align: "right", render: (row) => number.format(row.impressions) },
      { key: "ctr", header: "CTR", align: "right", render: (row) => pct(row.ctr) },
      { key: "availability", header: "Availability", render: (row) => row.availability || "-" },
      { key: "status", header: "Status", render: (row) => row.merchant_status || "-" },
      { key: "sales", header: "Sales match", render: (row) => (row.has_opencart_sales ? "Yes" : "No") },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  const operationColumns: Column<OperationRow>[] = useMemo(
    () => [
      { key: "label", header: "Name", render: (row) => row.label ?? row.status ?? "-" },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) },
      { key: "aov", header: "AOV", align: "right", render: (row) => (row.aov === undefined ? "-" : currency.format(row.aov)) },
      {
        key: "sale",
        header: "Counts",
        render: (row) =>
          row.counts_as_sale === undefined ? "-" : <StatusBadge value={row.counts_as_sale ? "success" : "skipped"} />
      }
    ],
    []
  );

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
        <DataTable rows={audit.priority_actions} columns={actionColumns} empty="No priority findings for this period." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Tracking health</h2>
          <span>Attribution sources compared to OpenCart truth</span>
        </div>
        <DataTable rows={audit.tracking.rows} columns={trackingColumns} empty="No tracking data yet." />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>Campaign audit</h2>
            <span>Meta and Google Ads</span>
          </div>
          <DataTable rows={audit.campaigns} columns={campaignColumns} empty="No campaign data yet." />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>GA4 channel audit</h2>
            <span>Traffic quality and revenue signals</span>
          </div>
          <DataTable rows={audit.channels} columns={channelColumns} empty="No GA4 channel data yet." />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Product opportunities</h2>
          <span>Distinct orders are treated as stronger demand than bulk quantity</span>
        </div>
        <DataTable rows={audit.products} columns={productColumns} empty="No product audit data yet." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Merchant feed audit</h2>
          <span>Products with visibility, clicks, sales match and feed risk</span>
        </div>
        <DataTable rows={audit.feed} columns={feedColumns} empty="No Merchant Center data yet." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>OpenCart operations audit</h2>
          <span>Status, payment, shipping and order changes</span>
        </div>
        <div className="operation-grid">
          <div>
            <h3>Order statuses</h3>
            <DataTable rows={audit.operations.statuses} columns={operationColumns} empty="No statuses found." />
          </div>
          <div>
            <h3>Payment methods</h3>
            <DataTable rows={audit.operations.payments} columns={operationColumns} empty="No payment data found." />
          </div>
          <div>
            <h3>Shipping methods</h3>
            <DataTable rows={audit.operations.shipping} columns={operationColumns} empty="No shipping data found." />
          </div>
          <div>
            <h3>Regions</h3>
            <DataTable rows={audit.operations.regions} columns={operationColumns} empty="No region data found." />
          </div>
          <div>
            <h3>Customer groups</h3>
            <DataTable rows={audit.operations.customer_groups} columns={operationColumns} empty="No customer group data found." />
          </div>
          <div>
            <h3>Detected order changes</h3>
            <DataTable
              rows={audit.operations.changes}
              empty="No order changes detected in this period."
              columns={[
                { key: "field", header: "Field", render: (row) => row.field },
                { key: "changes", header: "Changes", align: "right", render: (row) => number.format(row.changes) },
                { key: "last", header: "Last detected", render: (row) => formatDateTime(row.last_detected_at) }
              ]}
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
