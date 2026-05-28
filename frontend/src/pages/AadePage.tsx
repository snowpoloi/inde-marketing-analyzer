import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, FileText, Landmark, List, RefreshCw, ReceiptText, Scale, TrendingUp } from "lucide-react";
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

type AadeLineItem = {
  source: string;
  line_number: string | null;
  description: string | null;
  quantity: number | null;
  measurement_unit: string | null;
  unit_price: number;
  net_value: number;
  vat_amount: number;
  gross_value: number;
  vat_category: string | null;
  classification: string | null;
  line_type: string;
};

type OpenCartLineItem = {
  source: string;
  line_type: string;
  name: string;
  sku: string | null;
  model: string | null;
  brand: string | null;
  category: string | null;
  quantity: number;
  unit_price: number;
  line_total: number;
};

type OpenCartOrderMatch = {
  order_id: string;
  date_added: string;
  status: string | null;
  sub_total: number;
  tax: number;
  shipping: number;
  total: number;
  shipping_title: string | null;
  shipping_method: string | null;
  match_reason: string;
  lines: OpenCartLineItem[];
};

type AadeLedgerRow = {
  source_endpoint: string;
  record_type: string;
  direction: string;
  invoice_type: string;
  document_count: number;
  mark: string | null;
  uid: string | null;
  issue_date: string;
  issuer_vat: string | null;
  issuer_name: string | null;
  counterpart_vat: string | null;
  series: string | null;
  aa: string | null;
  currency: string;
  net_value: number;
  vat_amount: number;
  gross_value: number;
  is_cancelled: boolean;
  cancelled_by_mark: string | null;
  identity_key: string;
  line_items: AadeLineItem[];
  opencart_order: OpenCartOrderMatch | null;
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

const recordTypeLabels: Record<string, string> = {
  full_document: "Full document",
  book_info: "Book row",
  vat_info: "VAT row",
  cancellation: "Cancellation"
};

function pct(value: number) {
  return `${number.format(value)}%`;
}

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function downloadCsv(filename: string, rows: AadeLedgerRow[]) {
  const headers = [
    "Date",
    "Direction",
    "Invoice type",
    "Record type",
    "Issuer AFM",
    "Issuer company",
    "Counterpart AFM",
    "Series",
    "Number",
    "MARK",
    "UID",
    "Docs",
    "Net",
    "VAT",
    "Gross",
    "Cancelled",
    "Cancelled by MARK",
    "Source"
  ];
  const lines = [
    headers.map(csvCell).join(";"),
    ...rows.map((row) =>
      [
        row.issue_date,
        row.direction,
        formatAadeInvoiceType(row.invoice_type),
        recordTypeLabels[row.record_type] ?? row.record_type,
        row.issuer_vat,
        row.issuer_name,
        row.counterpart_vat,
        row.series,
        row.aa,
        row.mark,
        row.uid,
        row.document_count,
        row.net_value,
        row.vat_amount,
        row.gross_value,
        row.is_cancelled ? "Yes" : "No",
        row.cancelled_by_mark,
        row.source_endpoint
      ].map(csvCell).join(";")
    )
  ];
  const blob = new Blob([`\uFEFF${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function invoiceLabel(row: AadeLedgerRow) {
  return [row.series, row.aa].filter(Boolean).join(" / ") || row.mark || row.uid || row.identity_key;
}

function downloadInvoiceLinesCsv(row: AadeLedgerRow) {
  const headers = [
    "Source",
    "Invoice",
    "MARK",
    "Line",
    "Type",
    "Description",
    "SKU",
    "Model",
    "Qty",
    "Unit",
    "Unit price",
    "Net",
    "VAT",
    "Gross"
  ];
  const aadeLines = row.line_items.map((line) => [
    "AADE",
    invoiceLabel(row),
    row.mark,
    line.line_number,
    line.line_type,
    line.description,
    "",
    "",
    line.quantity ?? "",
    line.measurement_unit,
    line.unit_price,
    line.net_value,
    line.vat_amount,
    line.gross_value
  ]);
  const openCartLines = (row.opencart_order?.lines ?? []).map((line) => [
    "OpenCart",
    row.opencart_order?.order_id,
    row.mark,
    "",
    line.line_type,
    line.name,
    line.sku,
    line.model,
    line.quantity,
    "",
    line.unit_price,
    "",
    "",
    line.line_total
  ]);
  const lines = [
    headers.map(csvCell).join(";"),
    ...[...aadeLines, ...openCartLines].map((line) => line.map(csvCell).join(";"))
  ];
  const blob = new Blob([`\uFEFF${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `aade-invoice-lines-${invoiceLabel(row).replace(/[^a-z0-9_-]+/gi, "-")}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function AadePage() {
  const [dateFrom, setDateFrom] = useState(isoDate(-1));
  const [dateTo, setDateTo] = useState(isoDate());
  const [activePreset, setActivePreset] = useState("");
  const [aade, setAade] = useState<AadeAudit>(emptyAade);
  const [ledgerRows, setLedgerRows] = useState<AadeLedgerRow[]>([]);
  const [directionFilter, setDirectionFilter] = useState("all");
  const [invoiceTypeFilter, setInvoiceTypeFilter] = useState("all");
  const [recordTypeFilter, setRecordTypeFilter] = useState("full_document");
  const [ledgerSearch, setLedgerSearch] = useState("");
  const [selectedIdentityKey, setSelectedIdentityKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load(nextFrom = dateFrom, nextTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const [auditResult, ledgerResult] = await Promise.all([
        api.dashboard("audit", nextFrom, nextTo),
        api.dashboard("aade-documents", nextFrom, nextTo)
      ]);
      setAade({ ...emptyAade, ...(auditResult.data?.aade ?? {}) });
      setLedgerRows(Array.isArray(ledgerResult.data?.rows) ? ledgerResult.data.rows : []);
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

  const invoiceTypeOptions = useMemo(
    () =>
      [...new Set(ledgerRows.map((row) => row.invoice_type).filter(Boolean))].sort((left, right) =>
        formatAadeInvoiceType(left).localeCompare(formatAadeInvoiceType(right), "el", { numeric: true })
      ),
    [ledgerRows]
  );

  const visibleLedgerRows = useMemo(() => {
    const needle = ledgerSearch.trim().toLowerCase();
    return ledgerRows.filter((row) => {
      if (directionFilter !== "all" && row.direction !== directionFilter) {
        return false;
      }
      if (invoiceTypeFilter !== "all" && row.invoice_type !== invoiceTypeFilter) {
        return false;
      }
      if (recordTypeFilter !== "all" && row.record_type !== recordTypeFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return [
        row.mark,
        row.uid,
        row.issuer_vat,
        row.issuer_name,
        row.counterpart_vat,
        row.series,
        row.aa,
        row.invoice_type,
        formatAadeInvoiceType(row.invoice_type)
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [directionFilter, invoiceTypeFilter, ledgerRows, ledgerSearch, recordTypeFilter]);

  const selectedLedgerRow = useMemo(
    () => visibleLedgerRows.find((row) => row.identity_key === selectedIdentityKey) ?? null,
    [selectedIdentityKey, visibleLedgerRows]
  );

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
      {
        key: "invoice",
        header: "Invoice type",
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

  const aadeLineColumns: Column<AadeLineItem>[] = useMemo(
    () => [
      { key: "line", header: "Line", render: (row) => row.line_number || "-" },
      {
        key: "description",
        header: "Description",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.description || "No product description in AADE"}</strong>
            <span>{[row.classification, row.vat_category ? `VAT ${row.vat_category}` : ""].filter(Boolean).join(" | ")}</span>
          </div>
        )
      },
      { key: "type", header: "Type", render: (row) => row.line_type },
      { key: "qty", header: "Qty", align: "right", render: (row) => (row.quantity === null ? "-" : number.format(row.quantity)) },
      { key: "unit", header: "Unit", render: (row) => row.measurement_unit || "-" },
      { key: "unit_price", header: "Unit price", align: "right", render: (row) => currency.format(row.unit_price) },
      { key: "net", header: "Net", align: "right", render: (row) => currency.format(row.net_value) },
      { key: "vat", header: "VAT", align: "right", render: (row) => currency.format(row.vat_amount) },
      { key: "gross", header: "Gross", align: "right", render: (row) => currency.format(row.gross_value) }
    ],
    []
  );

  const openCartLineColumns: Column<OpenCartLineItem>[] = useMemo(
    () => [
      {
        key: "product",
        header: "Product / shipping",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.name}</strong>
            <span>{[row.sku, row.model, row.brand, row.category].filter(Boolean).join(" | ")}</span>
          </div>
        )
      },
      { key: "type", header: "Type", render: (row) => row.line_type },
      { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
      { key: "unit_price", header: "Unit price", align: "right", render: (row) => currency.format(row.unit_price) },
      { key: "line_total", header: "Line total", align: "right", render: (row) => currency.format(row.line_total) }
    ],
    []
  );

  const ledgerColumns: Column<AadeLedgerRow>[] = useMemo(
    () => [
      { key: "date", header: "Date", render: (row) => row.issue_date },
      { key: "direction", header: "Direction", render: (row) => <strong>{row.direction}</strong> },
      {
        key: "invoice",
        header: "Invoice type",
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
      { key: "record", header: "Record", render: (row) => recordTypeLabels[row.record_type] ?? row.record_type },
      { key: "issuer", header: "Issuer AFM", render: (row) => row.issuer_vat || "-" },
      { key: "issuer_name", header: "Issuer company", render: (row) => row.issuer_name || "-" },
      { key: "counterpart", header: "Counterpart AFM", render: (row) => row.counterpart_vat || "-" },
      { key: "invoice_no", header: "Series / No", render: (row) => [row.series, row.aa].filter(Boolean).join(" / ") || "-" },
      { key: "mark", header: "MARK", render: (row) => row.mark || "-" },
      { key: "docs", header: "Docs", align: "right", render: (row) => number.format(row.document_count) },
      { key: "net", header: "Net", align: "right", render: (row) => currency.format(row.net_value) },
      { key: "vat", header: "VAT", align: "right", render: (row) => currency.format(row.vat_amount) },
      { key: "gross", header: "Gross", align: "right", render: (row) => currency.format(row.gross_value) },
      {
        key: "lines",
        header: "Lines",
        render: (row) => {
          const lineCount = row.line_items.length + (row.opencart_order?.lines.length ?? 0);
          const selected = row.identity_key === selectedIdentityKey;
          return (
            <button
              className="secondary-action compact"
              onClick={() => setSelectedIdentityKey(selected ? "" : row.identity_key)}
            >
              <List size={15} />
              {lineCount ? number.format(lineCount) : "View"}
            </button>
          );
        }
      },
      {
        key: "status",
        header: "Status",
        render: (row) =>
          row.is_cancelled ? <span className="badge badge-failed">Cancelled</span> : <StatusBadge value="success" />
      }
    ],
    [selectedIdentityKey]
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

      <section className="panel">
        <div className="panel-title">
          <h2>Document ledger</h2>
          <span>{number.format(visibleLedgerRows.length)} visible rows</span>
        </div>
        <div className="sync-controls">
          <select value={directionFilter} onChange={(event) => setDirectionFilter(event.target.value)}>
            <option value="all">All directions</option>
            <option value="income">Income</option>
            <option value="expense">Expenses</option>
            <option value="vat">VAT</option>
          </select>
          <select value={invoiceTypeFilter} onChange={(event) => setInvoiceTypeFilter(event.target.value)}>
            <option value="all">All invoice types</option>
            {invoiceTypeOptions.map((code) => (
              <option key={code} value={code}>
                {formatAadeInvoiceType(code)}
              </option>
            ))}
          </select>
          <select value={recordTypeFilter} onChange={(event) => setRecordTypeFilter(event.target.value)}>
            <option value="all">All records</option>
            <option value="full_document">Full documents</option>
            <option value="book_info">Book rows</option>
            <option value="vat_info">VAT rows</option>
            <option value="cancellation">Cancellations</option>
          </select>
          <input
            value={ledgerSearch}
            onChange={(event) => setLedgerSearch(event.target.value)}
            placeholder="AFM, company, MARK, series..."
          />
          <button
            className="secondary-action compact"
            onClick={() => downloadCsv(`aade-documents-${dateFrom}-${dateTo}.csv`, visibleLedgerRows)}
            disabled={visibleLedgerRows.length === 0}
          >
            <Download size={17} />
            Export CSV
          </button>
        </div>
        <DataTable rows={visibleLedgerRows} columns={ledgerColumns} empty="No AADE document rows for this period." />
        {selectedLedgerRow ? (
          <div className="invoice-detail-panel">
            <div className="panel-title">
              <div>
                <h2>Invoice lines</h2>
                <p>
                  {selectedLedgerRow.issue_date} | {selectedLedgerRow.direction} | {formatAadeInvoiceType(selectedLedgerRow.invoice_type)} | {invoiceLabel(selectedLedgerRow)}
                </p>
              </div>
              <button
                className="secondary-action compact"
                onClick={() => downloadInvoiceLinesCsv(selectedLedgerRow)}
                disabled={selectedLedgerRow.line_items.length === 0 && !selectedLedgerRow.opencart_order}
              >
                <Download size={17} />
                Export lines
              </button>
            </div>

            <div className="detail-summary">
              <span>Issuer: {selectedLedgerRow.issuer_vat || "-"} {selectedLedgerRow.issuer_name ? `| ${selectedLedgerRow.issuer_name}` : ""}</span>
              <span>Counterpart: {selectedLedgerRow.counterpart_vat || "-"}</span>
              <span>MARK: {selectedLedgerRow.mark || "-"}</span>
              <span>Total: {currency.format(selectedLedgerRow.gross_value)}</span>
            </div>

            <div className="detail-grid">
              <section>
                <div className="panel-title tight">
                  <h2>AADE document lines</h2>
                  <span>{number.format(selectedLedgerRow.line_items.length)} rows</span>
                </div>
                <DataTable
                  rows={selectedLedgerRow.line_items}
                  columns={aadeLineColumns}
                  empty="No product line details were included in this AADE payload."
                />
              </section>

              <section>
                <div className="panel-title tight">
                  <h2>OpenCart products and shipping</h2>
                  <span>
                    {selectedLedgerRow.opencart_order
                      ? `Order ${selectedLedgerRow.opencart_order.order_id} | ${selectedLedgerRow.opencart_order.match_reason}`
                      : "No matched order"}
                  </span>
                </div>
                {selectedLedgerRow.opencart_order ? (
                  <>
                    <div className="detail-summary">
                      <span>Status: {selectedLedgerRow.opencart_order.status || "-"}</span>
                      <span>Products: {currency.format(selectedLedgerRow.opencart_order.sub_total)}</span>
                      <span>Shipping: {currency.format(selectedLedgerRow.opencart_order.shipping)}</span>
                      <span>Total: {currency.format(selectedLedgerRow.opencart_order.total)}</span>
                    </div>
                    <DataTable
                      rows={selectedLedgerRow.opencart_order.lines}
                      columns={openCartLineColumns}
                      empty="No OpenCart products found for the matched order."
                    />
                  </>
                ) : (
                  <div className="empty-state">No OpenCart order matched this AADE document.</div>
                )}
              </section>
            </div>
          </div>
        ) : null}
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
