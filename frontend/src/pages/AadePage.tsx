import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileText, Landmark, RefreshCw, ReceiptText, Scale, TrendingUp } from "lucide-react";
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
  title: string;
  severity: string;
  action: string;
  reason: string;
  metric: string;
  value: string | number;
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

type AadeAudit = {
  summary: AadeSummary;
  documents: AadeDocumentRow[];
  mismatches: AuditAction[];
};

type AadeMetric = {
  metric: string;
  value: string;
  detail: string;
};

const emptyAade: AadeAudit = {
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
};

function pct(value: number) {
  return `${number.format(value)}%`;
}

export function AadePage() {
  const [dateFrom, setDateFrom] = useState(isoDate(-1));
  const [dateTo, setDateTo] = useState(isoDate());
  const [activePreset, setActivePreset] = useState("");
  const [aade, setAade] = useState<AadeAudit>(emptyAade);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load(nextFrom = dateFrom, nextTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const result = await api.dashboard("audit", nextFrom, nextTo);
      setAade({ ...emptyAade, ...(result.data?.aade ?? {}) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load AADE data");
    } finally {
      setLoading(false);
    }
  }

  function applyPreset(preset: DatePreset) {
    const range = presetRange(preset);
    setDateFrom(range.from);
    setDateTo(range.to);
    setActivePreset(preset.key);
    load(range.from, range.to);
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const summaryRows = useMemo<AadeMetric[]>(
    () => [
      {
        metric: "Fiscal income",
        value: currency.format(aade.summary.income_gross),
        detail: `${number.format(aade.summary.income_documents)} docs, ${currency.format(aade.summary.income_vat)} VAT`
      },
      {
        metric: "Fiscal expenses",
        value: currency.format(aade.summary.expense_gross),
        detail: `${number.format(aade.summary.expense_documents)} docs, ${currency.format(aade.summary.expense_vat)} VAT`
      },
      {
        metric: "Cancelled documents",
        value: number.format(aade.summary.cancelled_documents),
        detail: "Marked cancelled in myDATA"
      },
      {
        metric: "OpenCart revenue",
        value: currency.format(aade.summary.opencart_revenue),
        detail: `${number.format(aade.summary.opencart_orders)} orders`
      },
      {
        metric: "Revenue gap",
        value: currency.format(aade.summary.revenue_gap),
        detail: pct(aade.summary.revenue_gap_percent)
      }
    ],
    [aade.summary]
  );

  const summaryColumns: Column<AadeMetric>[] = useMemo(
    () => [
      { key: "metric", header: "Metric", render: (row) => <strong>{row.metric}</strong> },
      { key: "value", header: "Value", align: "right", render: (row) => row.value },
      { key: "detail", header: "Detail", render: (row) => row.detail }
    ],
    []
  );

  const findingColumns: Column<AuditAction>[] = useMemo(
    () => [
      { key: "severity", header: "Severity", render: (row) => <StatusBadge value={row.severity} /> },
      {
        key: "title",
        header: "Finding",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.title}</strong>
            <span>{row.metric}: {row.value}</span>
          </div>
        )
      },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  const documentColumns: Column<AadeDocumentRow>[] = useMemo(
    () => [
      { key: "direction", header: "Direction", render: (row) => <strong>{row.direction}</strong> },
      { key: "invoice", header: "Invoice type", render: (row) => row.invoice_type || "-" },
      { key: "documents", header: "Docs", align: "right", render: (row) => number.format(row.documents) },
      { key: "cancelled", header: "Cancelled", align: "right", render: (row) => number.format(row.cancelled_documents) },
      { key: "net", header: "Net", align: "right", render: (row) => currency.format(row.net_value) },
      { key: "vat", header: "VAT", align: "right", render: (row) => currency.format(row.vat_amount) },
      { key: "gross", header: "Gross", align: "right", render: (row) => currency.format(row.gross_value) },
      { key: "action", header: "Action", render: (row) => <StatusBadge value={row.audit_action} /> },
      { key: "reason", header: "Reason", render: (row) => row.reason }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>AADE myDATA</h1>
          <p>Fiscal documents, VAT and OpenCart reconciliation from read-only myDATA pulls.</p>
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
        <StatCard label="Fiscal income" value={currency.format(aade.summary.income_gross)} detail={`${number.format(aade.summary.income_documents)} income docs`} icon={ReceiptText} />
        <StatCard label="Fiscal expenses" value={currency.format(aade.summary.expense_gross)} detail={`${number.format(aade.summary.expense_documents)} expense docs`} icon={FileText} />
        <StatCard label="VAT balance" value={currency.format(aade.summary.income_vat - aade.summary.expense_vat)} detail={`${currency.format(aade.summary.income_vat)} income VAT`} icon={Landmark} />
        <StatCard label="OpenCart gap" value={currency.format(aade.summary.revenue_gap)} detail={pct(aade.summary.revenue_gap_percent)} icon={Scale} />
        <StatCard label="Cancelled" value={number.format(aade.summary.cancelled_documents)} detail="myDATA cancelled documents" icon={AlertTriangle} />
        <StatCard label="OpenCart revenue" value={currency.format(aade.summary.opencart_revenue)} detail={`${number.format(aade.summary.opencart_orders)} orders`} icon={TrendingUp} />
      </section>

      <div className="two-column">
        <section className="panel">
          <div className="panel-title">
            <h2>Fiscal summary</h2>
            <span>Only AADE/myDATA totals</span>
          </div>
          <DataTable rows={summaryRows} columns={summaryColumns} empty="No AADE summary yet." />
        </section>
        <section className="panel">
          <div className="panel-title">
            <h2>Fiscal findings</h2>
            <span>Revenue gap and cancellation checks</span>
          </div>
          <DataTable rows={aade.mismatches} columns={findingColumns} empty="No AADE findings for this period." />
        </section>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Document groups</h2>
          <span>Income and expense documents by invoice type</span>
        </div>
        <DataTable rows={aade.documents} columns={documentColumns} empty="No AADE documents yet." />
      </section>
    </div>
  );
}
