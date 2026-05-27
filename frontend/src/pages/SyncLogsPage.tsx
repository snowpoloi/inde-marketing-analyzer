import { FormEvent, useEffect, useState } from "react";
import { Play, Upload } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { SyncRun } from "../api/client";
import type { Column } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

const providers = ["meta_ads", "google_ads", "ga4", "merchant_center", "search_console", "aade", "opencart", "shoply"];
const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

function syncDetails(row: SyncRun) {
  const meta = row.meta || {};
  const details: string[] = [];
  if (meta.product_catalog_records !== undefined) {
    details.push(`Products: ${String(meta.product_catalog_records)}`);
  }
  if (meta.order_records !== undefined) {
    details.push(`Orders: ${String(meta.order_records)}`);
  }
  if (meta.order_product_updates !== undefined) {
    details.push(`Updated products: ${String(meta.order_product_updates)}`);
  }
  if (meta.product_feed_error) {
    details.push(`Feed error: ${String(meta.product_feed_error)}`);
  }
  if (meta.ga4_rows !== undefined) {
    details.push(`GA4 rows: ${number.format(Number(meta.ga4_rows) || 0)}`);
  }
  if (meta.ga4_purchases !== undefined) {
    details.push(`GA4 purchases: ${number.format(Number(meta.ga4_purchases) || 0)}`);
  }
  if (meta.ga4_purchase_revenue !== undefined) {
    details.push(`GA4 revenue: ${currency.format(Number(meta.ga4_purchase_revenue) || 0)}`);
  }
  if (meta.merchant_rows !== undefined) {
    details.push(`Merchant rows: ${number.format(Number(meta.merchant_rows) || 0)}`);
  }
  if (meta.merchant_clicks !== undefined) {
    details.push(`Merchant clicks: ${number.format(Number(meta.merchant_clicks) || 0)}`);
  }
  if (meta.merchant_impressions !== undefined) {
    details.push(`Merchant impressions: ${number.format(Number(meta.merchant_impressions) || 0)}`);
  }
  if (meta.merchant_disapproved !== undefined || meta.merchant_limited !== undefined || meta.merchant_pending !== undefined) {
    details.push(
      `Merchant issues: ${number.format(Number(meta.merchant_disapproved) || 0)} disapproved, ${number.format(
        Number(meta.merchant_limited) || 0
      )} limited, ${number.format(Number(meta.merchant_pending) || 0)} pending`
    );
  }
  if (meta.search_console_rows !== undefined) {
    details.push(`Search Console rows: ${number.format(Number(meta.search_console_rows) || 0)}`);
  }
  if (meta.search_console_clicks !== undefined) {
    details.push(`Search Console clicks: ${number.format(Number(meta.search_console_clicks) || 0)}`);
  }
  if (meta.search_console_impressions !== undefined) {
    details.push(`Search Console impressions: ${number.format(Number(meta.search_console_impressions) || 0)}`);
  }
  if (meta.aade_documents !== undefined) {
    details.push(`AADE documents: ${number.format(Number(meta.aade_documents) || 0)}`);
  }
  if (meta.aade_full_documents !== undefined) {
    details.push(`AADE full docs: ${number.format(Number(meta.aade_full_documents) || 0)}`);
  }
  if (meta.aade_book_documents !== undefined) {
    details.push(`AADE book docs: ${number.format(Number(meta.aade_book_documents) || 0)}`);
  }
  if (meta.aade_book_rows !== undefined) {
    details.push(`AADE book rows: ${number.format(Number(meta.aade_book_rows) || 0)}`);
  }
  if (meta.aade_vat_rows !== undefined) {
    details.push(`AADE VAT rows: ${number.format(Number(meta.aade_vat_rows) || 0)}`);
  }
  if (meta.aade_vat_amount !== undefined) {
    details.push(`AADE VAT amount: ${currency.format(Number(meta.aade_vat_amount) || 0)}`);
  }
  if (meta.aade_summary_rows !== undefined) {
    details.push(`AADE summary rows: ${number.format(Number(meta.aade_summary_rows) || 0)}`);
  }
  if (meta.aade_calls !== undefined) {
    details.push(`AADE calls: ${number.format(Number(meta.aade_calls) || 0)}`);
  }
  if (meta.aade_pages !== undefined) {
    details.push(`AADE pages: ${number.format(Number(meta.aade_pages) || 0)}`);
  }
  if (Array.isArray(meta.aade_endpoint_results)) {
    const endpointDetails = meta.aade_endpoint_results
      .map((item) => {
        const result = item as Record<string, unknown>;
        const name = String(result.endpoint || "unknown");
        const calls = Number(result.calls) || 0;
        const full = Number(result.full_documents) || 0;
        const book = Number(result.book_documents) || 0;
        const vat = Number(result.vat_rows) || 0;
        return `${name}: ${number.format(calls)} calls, ${number.format(full)} full, ${number.format(book)} book, ${number.format(vat)} VAT`;
      })
      .join("; ");
    if (endpointDetails) {
      details.push(`AADE endpoints: ${endpointDetails}`);
    }
  }
  if (meta.aade_gross_income !== undefined) {
    details.push(`AADE income: ${currency.format(Number(meta.aade_gross_income) || 0)}`);
  }
  if (meta.aade_gross_expenses !== undefined) {
    details.push(`AADE expenses: ${currency.format(Number(meta.aade_gross_expenses) || 0)}`);
  }
  if (meta.aade_cancelled_documents !== undefined) {
    details.push(`AADE cancelled: ${number.format(Number(meta.aade_cancelled_documents) || 0)}`);
  }
  return details.length ? details.join(" | ") : "-";
}

export function SyncLogsPage() {
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [dateTo, setDateTo] = useState(isoDate());
  const [dateFrom, setDateFrom] = useState(isoDate(-1));
  const [selectedProviders, setSelectedProviders] = useState(providers);
  const [googleFile, setGoogleFile] = useState<File | null>(null);
  const [metaFile, setMetaFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    setRuns(await api.syncRuns());
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Could not load sync logs"));
  }, []);

  async function trigger() {
    setMessage("");
    await api.triggerSync(selectedProviders, dateFrom, dateTo);
    await load();
  }

  async function importFile(event: FormEvent, kind: "google" | "meta") {
    event.preventDefault();
    const file = kind === "google" ? googleFile : metaFile;
    if (!file) {
      setMessage("Select a CSV file first.");
      return;
    }
    await api.importCsv(kind, dateTo, file);
    setMessage(`${file.name} imported.`);
    await load();
  }

  const columns: Column<SyncRun>[] = [
    { key: "provider", header: "Provider", render: (row) => row.provider },
    { key: "type", header: "Type", render: (row) => row.sync_type },
    { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> },
    { key: "period", header: "Period", render: (row) => `${row.date_from ?? "-"} to ${row.date_to ?? "-"}` },
    { key: "records", header: "Records", align: "right", render: (row) => row.records_processed },
    { key: "details", header: "Details", render: syncDetails },
    { key: "started", header: "Started", render: (row) => new Date(row.started_at).toLocaleString("el-GR") },
    { key: "error", header: "Error", render: (row) => row.error_message || "-" }
  ];

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Sync logs</h1>
          <p>Daily worker runs, manual syncs, and CSV imports.</p>
        </div>
      </header>
      {message ? <div className="notice">{message}</div> : null}

      <section className="panel">
        <div className="panel-title">
          <h2>Manual sync</h2>
          <span>Read-only provider pull</span>
        </div>
        <div className="sync-controls">
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <div className="provider-pills">
            {providers.map((provider) => (
              <label key={provider}>
                <input
                  type="checkbox"
                  checked={selectedProviders.includes(provider)}
                  onChange={() =>
                    setSelectedProviders((current) =>
                      current.includes(provider) ? current.filter((item) => item !== provider) : [...current, provider]
                    )
                  }
                />
                {provider}
              </label>
            ))}
          </div>
          <button className="primary-action compact" onClick={trigger}>
            <Play size={17} />
            Run sync
          </button>
        </div>
      </section>

      <div className="two-column">
        <form className="panel import-panel" onSubmit={(event) => importFile(event, "google")}>
          <div className="panel-title">
            <h2>Google Ads CSV</h2>
            <span>campaign_name, cost, clicks, conversions...</span>
          </div>
          <input type="file" accept=".csv,text/csv" onChange={(event) => setGoogleFile(event.target.files?.[0] ?? null)} />
          <button className="primary-action compact">
            <Upload size={17} />
            Import
          </button>
        </form>
        <form className="panel import-panel" onSubmit={(event) => importFile(event, "meta")}>
          <div className="panel-title">
            <h2>Meta Ads CSV</h2>
            <span>date, campaign, adset, ad, spend...</span>
          </div>
          <input type="file" accept=".csv,text/csv" onChange={(event) => setMetaFile(event.target.files?.[0] ?? null)} />
          <button className="primary-action compact">
            <Upload size={17} />
            Import
          </button>
        </form>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Run history</h2>
          <span>Latest 100 entries</span>
        </div>
        <DataTable rows={runs} columns={columns} empty="No sync runs yet." />
      </section>
    </div>
  );
}
