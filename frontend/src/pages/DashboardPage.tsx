import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Banknote, MousePointerClick, ReceiptText, ShoppingCart, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

type PerformanceRow = {
  source?: string;
  campaign_id: string | null;
  campaign_name: string;
  cost: number;
  clicks: number;
  impressions: number;
  conversions: number;
  conversion_value: number;
  roas: number;
  cpc: number;
  ctr: number;
};

type RecommendationRow = {
  source: string;
  campaign_name: string;
  action: string;
  severity: string;
  reason: string;
  metrics: PerformanceRow;
};

export function DashboardPage() {
  const today = isoDate();
  const [dateTo, setDateTo] = useState(today);
  const [dateFrom, setDateFrom] = useState(isoDate(-30));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<any>({});
  const [meta, setMeta] = useState<PerformanceRow[]>([]);
  const [google, setGoogle] = useState<PerformanceRow[]>([]);
  const [attribution, setAttribution] = useState<any[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationRow[]>([]);
  const [brandCategory, setBrandCategory] = useState<any>({ brands: [], categories: [] });
  const [products, setProducts] = useState<any[]>([]);
  const [salesDaily, setSalesDaily] = useState<any[]>([]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [summaryRes, metaRes, googleRes, attributionRes, recRes, brandRes, productRes, salesRes] = await Promise.all([
        api.dashboard("summary", dateFrom, dateTo),
        api.dashboard("meta-performance", dateFrom, dateTo),
        api.dashboard("google-performance", dateFrom, dateTo),
        api.dashboard("attribution", dateFrom, dateTo),
        api.dashboard("recommendations", dateFrom, dateTo),
        api.dashboard("brand-category", dateFrom, dateTo),
        api.dashboard("product-profitability", dateFrom, dateTo),
        api.dashboard("opencart-sales", dateFrom, dateTo)
      ]);
      setSummary(summaryRes.data);
      setMeta(metaRes.data.rows ?? []);
      setGoogle(googleRes.data.rows ?? []);
      setAttribution(attributionRes.data.rows ?? []);
      setRecommendations(recRes.data.rows ?? []);
      setBrandCategory(brandRes.data);
      setProducts(productRes.data.rows ?? []);
      setSalesDaily(salesRes.data.daily ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const performanceColumns: Column<PerformanceRow>[] = useMemo(
    () => [
      { key: "campaign", header: "Campaign", render: (row) => <strong>{row.campaign_name}</strong> },
      { key: "cost", header: "Cost", align: "right", render: (row) => currency.format(row.cost) },
      { key: "clicks", header: "Clicks", align: "right", render: (row) => number.format(row.clicks) },
      { key: "conv", header: "Conv.", align: "right", render: (row) => number.format(row.conversions) },
      { key: "value", header: "Value", align: "right", render: (row) => currency.format(row.conversion_value) },
      { key: "roas", header: "ROAS", align: "right", render: (row) => number.format(row.roas) },
      { key: "ctr", header: "CTR", align: "right", render: (row) => `${number.format(row.ctr)}%` }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Executive summary</h1>
          <p>OpenCart is treated as the source of truth for actual sales.</p>
        </div>
        <div className="date-controls">
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <button className="primary-action compact" onClick={load} disabled={loading}>
            <TrendingUp size={17} />
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="stats-grid">
        <StatCard label="Actual revenue" value={currency.format(summary.opencart_revenue ?? 0)} detail={`${number.format(summary.opencart_orders ?? 0)} orders`} icon={Banknote} />
        <StatCard label="Ad spend" value={currency.format(summary.ad_spend ?? 0)} detail={`${number.format(summary.ad_clicks ?? 0)} clicks`} icon={MousePointerClick} />
        <StatCard label="Actual ROAS" value={number.format(summary.actual_roas ?? 0)} detail="OpenCart revenue / spend" icon={TrendingUp} />
        <StatCard label="Attributed revenue" value={currency.format(summary.attributed_revenue ?? 0)} detail={`${number.format(summary.attributed_conversions ?? 0)} conversions`} icon={ReceiptText} />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Attribution comparison</h2>
          <span>Meta vs Google vs GA4 vs OpenCart</span>
        </div>
        <DataTable
          rows={attribution}
          empty="No attribution data yet."
          columns={[
            { key: "source", header: "Source", render: (row) => row.source },
            { key: "reported", header: "Reported", align: "right", render: (row) => number.format(row.reported) },
            { key: "actual", header: "OpenCart", align: "right", render: (row) => number.format(row.opencart_orders) },
            { key: "delta", header: "Delta", align: "right", render: (row) => number.format(row.delta) },
            { key: "percent", header: "Delta %", align: "right", render: (row) => `${number.format(row.delta_percent)}%` }
          ]}
        />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>Meta performance</h2>
            <span>Campaign level</span>
          </div>
          <DataTable rows={meta} columns={performanceColumns} empty="No Meta data loaded." />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>Google Ads performance</h2>
            <span>Campaign level</span>
          </div>
          <DataTable rows={google} columns={performanceColumns} empty="No Google Ads data loaded." />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Campaign recommendations</h2>
          <span>Scale, reduce, pause, investigate tracking/feed</span>
        </div>
        <DataTable
          rows={recommendations}
          empty="No recommendations yet."
          columns={[
            { key: "source", header: "Source", render: (row) => row.source },
            { key: "campaign", header: "Campaign", render: (row) => <strong>{row.campaign_name}</strong> },
            { key: "action", header: "Action", render: (row) => <StatusBadge value={row.action} /> },
            { key: "severity", header: "Severity", render: (row) => <StatusBadge value={row.severity} /> },
            { key: "reason", header: "Reason", render: (row) => row.reason }
          ]}
        />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>Brand performance</h2>
            <span>OpenCart products</span>
          </div>
          <DataTable
            rows={brandCategory.brands ?? []}
            empty="No brand sales yet."
            columns={[
              { key: "brand", header: "Brand", render: (row) => row.brand },
              { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
              { key: "rev", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) }
            ]}
          />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>Category performance</h2>
            <span>OpenCart products</span>
          </div>
          <DataTable
            rows={brandCategory.categories ?? []}
            empty="No category sales yet."
            columns={[
              { key: "category", header: "Category", render: (row) => row.category },
              { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
              { key: "rev", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) }
            ]}
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Product-level profitability hints</h2>
          <span>OpenCart sales plus Merchant feed signals</span>
        </div>
        <DataTable
          rows={products}
          empty="No product data yet."
          columns={[
            { key: "name", header: "Product", render: (row) => <strong>{row.name}</strong> },
            { key: "sku", header: "SKU", render: (row) => row.sku || row.product_id || "-" },
            { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
            { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders ?? 0) },
            { key: "qpo", header: "Qty/order", align: "right", render: (row) => number.format(row.average_quantity_per_order ?? 0) },
            { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) },
            { key: "hint", header: "Hint", render: (row) => <StatusBadge value={row.hint} /> },
            { key: "reason", header: "Reason", render: (row) => row.reason }
          ]}
        />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>OpenCart actual sales</h2>
          <span>Daily revenue</span>
        </div>
        <div className="daily-bars">
          {salesDaily.length === 0 ? (
            <div className="empty-state">
              <ShoppingCart size={20} />
              No OpenCart sales loaded.
            </div>
          ) : (
            salesDaily.map((day) => (
              <div className="bar-row" key={day.date}>
                <span>{day.date}</span>
                <div>
                  <i style={{ width: `${Math.min(100, (day.revenue / Math.max(summary.opencart_revenue ?? 1, 1)) * 100)}%` }} />
                </div>
                <strong>{currency.format(day.revenue)}</strong>
              </div>
            ))
          )}
        </div>
      </section>

      {loading ? (
        <div className="loading-overlay">
          <AlertTriangle size={18} />
          Loading reports
        </div>
      ) : null}
    </div>
  );
}
