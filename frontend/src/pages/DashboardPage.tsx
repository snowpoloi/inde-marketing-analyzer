import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Banknote, MousePointerClick, ReceiptText, ShoppingCart, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import "../styles/date-presets.css";
import { DateRangeControls, useReportPeriod } from "../components/DateRangeControls";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("el-GR", { style: "percent", maximumFractionDigits: 2 });

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

type BrandRow = {
  brand: string;
  quantity: number;
  revenue: number;
};

type CategoryRow = {
  category: string;
  quantity: number;
  revenue: number;
};

type BrandCategoryData = {
  brands: BrandRow[];
  categories: CategoryRow[];
};

export function DashboardPage() {
  const { range, setRange } = useReportPeriod();
  const { from: dateFrom, to: dateTo } = range;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<any>({});
  const [meta, setMeta] = useState<PerformanceRow[]>([]);
  const [google, setGoogle] = useState<PerformanceRow[]>([]);
  const [tiktok, setTiktok] = useState<PerformanceRow[]>([]);
  const [attribution, setAttribution] = useState<any[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationRow[]>([]);
  const [brandCategory, setBrandCategory] = useState<BrandCategoryData>({ brands: [], categories: [] });
  const [products, setProducts] = useState<any[]>([]);
  const [salesDaily, setSalesDaily] = useState<any[]>([]);

  async function load(nextDateFrom = dateFrom, nextDateTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const [summaryRes, metaRes, googleRes, tiktokRes, attributionRes, recRes, brandRes, productRes, salesRes] = await Promise.all([
        api.dashboard("summary", nextDateFrom, nextDateTo),
        api.dashboard("meta-performance", nextDateFrom, nextDateTo),
        api.dashboard("google-performance", nextDateFrom, nextDateTo),
        api.dashboard("tiktok-performance", nextDateFrom, nextDateTo),
        api.dashboard("attribution", nextDateFrom, nextDateTo),
        api.dashboard("recommendations", nextDateFrom, nextDateTo),
        api.dashboard("brand-category", nextDateFrom, nextDateTo),
        api.dashboard("product-profitability", nextDateFrom, nextDateTo),
        api.dashboard("opencart-sales", nextDateFrom, nextDateTo)
      ]);
      setSummary(summaryRes.data);
      setMeta(metaRes.data.rows ?? []);
      setGoogle(googleRes.data.rows ?? []);
      setTiktok(tiktokRes.data.rows ?? []);
      setAttribution(attributionRes.data.rows ?? []);
      setRecommendations(recRes.data.rows ?? []);
      setBrandCategory({
        brands: brandRes.data.brands ?? [],
        categories: brandRes.data.categories ?? []
      });
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
          <DateRangeControls range={range} onChange={setRange} onPreset={next => load(next.from, next.to)} disabled={loading} />
          <button className="primary-action compact" onClick={() => load()} disabled={loading}>
            <TrendingUp size={17} />
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="stats-grid">
        <StatCard label="Actual revenue" value={currency.format(summary.opencart_revenue ?? 0)} detail={`${number.format(summary.opencart_orders ?? 0)} orders`} icon={Banknote} />
        <StatCard label="GA4 purchases" value={number.format(summary.ga4_purchases ?? 0)} detail={`${currency.format(summary.ga4_revenue ?? 0)} GA4 revenue`} icon={ShoppingCart} />
        <StatCard label="Ad spend" value={currency.format(summary.ad_spend ?? 0)} detail={`${number.format(summary.ad_clicks ?? 0)} clicks`} icon={MousePointerClick} />
        <StatCard label="Actual ROAS" value={number.format(summary.actual_roas ?? 0)} detail="OpenCart revenue / spend" icon={TrendingUp} />
        <StatCard label="Attributed revenue" value={currency.format(summary.attributed_revenue ?? 0)} detail={`${number.format(summary.attributed_conversions ?? 0)} conversions`} icon={ReceiptText} />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Attribution comparison</h2>
          <span>Meta vs Google vs TikTok vs GA4 vs OpenCart</span>
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
          <h2>TikTok Ads performance</h2>
          <span>Campaign level</span>
        </div>
        <DataTable rows={tiktok} columns={performanceColumns} empty="No TikTok Ads data loaded." />
      </section>

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
          <h2>Product profitability</h2>
          <span>Net sales and historical COGS, excluding supplier freight</span>
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
            { key: "net-sales", header: "Net sales", align: "right", render: (row) => row.net_sales === null ? "Unknown" : currency.format(row.net_sales) },
            { key: "cogs", header: "COGS", align: "right", render: (row) => (row.cogs === null || row.cogs === undefined ? "-" : currency.format(row.cogs)) },
            { key: "gross-profit", header: "Gross profit", align: "right", render: (row) => (row.gross_profit === null || row.gross_profit === undefined ? "-" : currency.format(row.gross_profit)) },
            { key: "margin", header: "Margin", align: "right", render: (row) => (row.margin_percent === null || row.margin_percent === undefined ? "-" : percent.format(row.margin_percent / 100)) },
            {
              key: "cogs-source",
              header: "COGS source",
              render: (row) => (
                <div className="stacked-cell">
                  <span>{row.cogs_source || "Unknown"}</span>
                  <small>{row.cogs_confidence === null ? "-" : percent.format(row.cogs_confidence)} confidence</small>
                  <small>{row.cogs_date || `${number.format(row.cost_coverage_percent ?? 0)}% coverage`}</small>
                </div>
              )
            },
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
