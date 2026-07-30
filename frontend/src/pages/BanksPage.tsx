import { useEffect, useMemo, useState } from "react";
import { Banknote, CopyX, Download, RefreshCw, Scale, TrendingDown, TrendingUp, Upload, WalletCards } from "lucide-react";
import { api } from "../api/client";
import type { BankDashboard, BankTransaction } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import "../styles/date-presets.css";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

type BankTab = "transactions" | "expenses" | "deposits";

const emptyDashboard: BankDashboard = {
  summary: {
    deposits: 0,
    expenses: 0,
    net_cashflow: 0,
    bank_fees: 0,
    transactions: 0,
    unmatched_deposits: 0,
    ignored_duplicates: 0,
    ignored_duplicate_amount: 0
  },
  expense_categories: [],
  bank_totals: [],
  deposits: [],
  transactions: []
};

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

function scopeLabel(scope: string | undefined) {
  switch (scope) {
    case "split":
      return "Split payment";
    case "remaining":
      return "Remaining balance";
    case "all":
      return "Products + shipping";
    case "products":
      return "Products only";
    case "shipping":
      return "Shipping only";
    case "overpaid":
      return "Overpaid";
    case "partial":
      return "Partial";
    default:
      return "Unmatched";
  }
}

function excelCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function downloadExcel(filename: string, headers: string[], rows: unknown[][]) {
  const tableRows = [
    `<tr>${headers.map((header) => `<th>${excelCell(header)}</th>`).join("")}</tr>`,
    ...rows.map((row) => `<tr>${row.map((cell) => `<td>${excelCell(cell)}</td>`).join("")}</tr>`)
  ].join("");
  const html = `<!doctype html><html><head><meta charset="utf-8" /></head><body><table>${tableRows}</table></body></html>`;
  const blob = new Blob([html], { type: "application/vnd.ms-excel;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function depositExportRows(rows: BankTransaction[]) {
  return rows.map((row) => [
    row.transaction_date,
    row.bank_name,
    row.amount,
    row.counterparty || "",
    row.description,
    row.reference || "",
    row.match?.order_id || "",
    scopeLabel(row.match?.payment_coverage),
    row.match?.order_total ?? "",
    row.match?.matched_bank_total ?? "",
    row.match?.product_amount ?? "",
    row.match?.shipping ?? "",
    row.match?.amount_gap ?? "",
    row.match?.related_transactions.map((related) => `${related.transaction_date} ${related.amount}`).join(" | ") || "",
    row.match?.match_reason || "unmatched",
    row.review_reason || ""
  ]);
}

function transactionExportRows(rows: BankTransaction[]) {
  return rows.map((row) => [
    row.transaction_date,
    row.value_date || "",
    row.bank_name,
    row.account || "",
    row.transaction_type,
    row.category,
    row.description,
    row.counterparty || "",
    row.reference || "",
    row.debit,
    row.credit,
    row.balance ?? "",
    row.source_filename
  ]);
}

export function BanksPage() {
  const [dateFrom, setDateFrom] = useState(isoDate(-29));
  const [dateTo, setDateTo] = useState(isoDate());
  const [activeTab, setActiveTab] = useState<BankTab>("transactions");
  const [dashboard, setDashboard] = useState<BankDashboard>(emptyDashboard);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function load(nextFrom = dateFrom, nextTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const result = await api.bankDashboard(nextFrom, nextTo);
      setDashboard(result.data ?? emptyDashboard);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load bank transactions");
    } finally {
      setLoading(false);
    }
  }

  async function importSelectedFile() {
    if (!file) {
      return;
    }
    setImporting(true);
    setError("");
    setNotice("");
    try {
      const result = await api.importBankFile(file);
      setNotice(
        `${result.filename}: imported ${number.format(result.imported)} of ${number.format(result.total)} rows, reconciled ${number.format(result.reconciled)} existing NBG movements, skipped ${number.format(result.skipped)} duplicates.`
      );
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import bank file");
    } finally {
      setImporting(false);
    }
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const expenseColumns: Column<BankDashboard["expense_categories"][number]>[] = useMemo(
    () => [
      { key: "category", header: "Category", render: (row) => <strong>{row.category}</strong> },
      { key: "transactions", header: "Transactions", align: "right", render: (row) => number.format(row.transactions) },
      { key: "amount", header: "Amount", align: "right", render: (row) => currency.format(row.amount) }
    ],
    []
  );

  const bankTotalsColumns: Column<BankDashboard["bank_totals"][number]>[] = useMemo(
    () => [
      { key: "bank", header: "Bank", render: (row) => <strong>{row.bank_name}</strong> },
      { key: "account", header: "Account", render: (row) => row.account },
      { key: "credits", header: "Credits", align: "right", render: (row) => currency.format(row.credits) },
      { key: "debits", header: "Debits", align: "right", render: (row) => currency.format(row.debits) },
      { key: "net", header: "Net cashflow", align: "right", render: (row) => currency.format(row.net_cashflow) },
      { key: "transactions", header: "Movements", align: "right", render: (row) => number.format(row.transactions) }
    ],
    []
  );

  const depositColumns: Column<BankTransaction>[] = useMemo(
    () => [
      { key: "date", header: "Date", render: (row) => row.transaction_date },
      { key: "bank", header: "Bank", render: (row) => row.bank_name },
      { key: "amount", header: "Amount", align: "right", render: (row) => currency.format(row.amount) },
      {
        key: "payer",
        header: "Payer / details",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.counterparty || "-"}</strong>
            <span>{row.description}</span>
          </div>
        )
      },
      { key: "reference", header: "Reference", render: (row) => row.reference || "-" },
      {
        key: "order",
        header: "Order",
        render: (row) =>
          row.match ? (
            <div className="audit-title-cell">
              <strong>{row.match.order_id}</strong>
              <span>
                {currency.format(row.match.order_total)} | matched {currency.format(row.match.matched_bank_total)} |{" "}
                {row.match.status || "-"}
              </span>
              {row.match.related_transactions.length ? (
                <span>
                  With {row.match.related_transactions
                    .map((related) => `${related.transaction_date} ${currency.format(related.amount)}`)
                    .join(", ")}
                </span>
              ) : null}
            </div>
          ) : (
            "-"
          )
      },
      { key: "scope", header: "Payment covers", render: (row) => <StatusBadge value={scopeLabel(row.match?.payment_coverage)} /> },
      {
        key: "gap",
        header: "Gap",
        align: "right",
        render: (row) => (row.match ? currency.format(row.match.amount_gap) : "-")
      },
      {
        key: "match",
        header: "Match",
        render: (row) => (
          <div className="audit-title-cell">
            <StatusBadge value={row.match?.match_reason || "manual review"} />
            {!row.match && row.review_reason ? <span>{row.review_reason}</span> : null}
          </div>
        )
      }
    ],
    []
  );

  const transactionColumns: Column<BankTransaction>[] = useMemo(
    () => [
      { key: "date", header: "Date", render: (row) => row.transaction_date },
      { key: "bank", header: "Bank", render: (row) => row.bank_name },
      { key: "type", header: "Type", render: (row) => <StatusBadge value={row.transaction_type} /> },
      { key: "category", header: "Category", render: (row) => row.category },
      {
        key: "details",
        header: "Details",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.description}</strong>
            <span>{[row.counterparty, row.reference].filter(Boolean).join(" | ") || row.source_filename}</span>
          </div>
        )
      },
      { key: "debit", header: "Debit", align: "right", render: (row) => (row.debit ? currency.format(row.debit) : "-") },
      { key: "credit", header: "Credit", align: "right", render: (row) => (row.credit ? currency.format(row.credit) : "-") },
      { key: "balance", header: "Balance", align: "right", render: (row) => (row.balance === null ? "-" : currency.format(row.balance)) }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Banks</h1>
          <p>Bank exports, expense analysis, deposit confirmations and OpenCart payment matching.</p>
        </div>
        <div className="date-controls">
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <button className="primary-action compact" onClick={() => load()} disabled={loading}>
            <RefreshCw size={17} />
            Refresh
          </button>
        </div>
      </header>

      {notice ? <div className="notice">{notice}</div> : null}
      {error ? <div className="notice error">{error}</div> : null}

      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>Upload bank export</h2>
            <span>CSV, XLS and XLSX exports from daily bank downloads.</span>
          </div>
          <span>{loading ? "Loading..." : `${number.format(dashboard.summary.transactions)} transactions loaded`}</span>
        </div>
        <div className="sync-controls">
          <input
            type="file"
            accept=".csv,.xls,.xlsx,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button className="primary-action compact" onClick={importSelectedFile} disabled={!file || importing}>
            <Upload size={17} />
            Import
          </button>
        </div>
      </section>

      <section className="stats-grid">
        <StatCard label="Deposits" value={currency.format(dashboard.summary.deposits)} detail={`${number.format(dashboard.deposits.length)} incoming payments`} icon={TrendingUp} />
        <StatCard label="Expenses" value={currency.format(dashboard.summary.expenses)} detail="Cash out by bank exports" icon={TrendingDown} />
        <StatCard label="Net cashflow" value={currency.format(dashboard.summary.net_cashflow)} detail="Deposits minus expenses" icon={Scale} />
        <StatCard label="Bank fees" value={currency.format(dashboard.summary.bank_fees)} detail="Detected commissions and fees" icon={Banknote} />
        <StatCard label="Unmatched deposits" value={number.format(dashboard.summary.unmatched_deposits)} detail="Need manual review before order release" icon={WalletCards} />
        <StatCard
          label="Ignored exact duplicates"
          value={number.format(dashboard.summary.ignored_duplicates)}
          detail={`${currency.format(dashboard.summary.ignored_duplicate_amount)} excluded from totals`}
          icon={CopyX}
        />
      </section>

      <section className="panel">
        <div className="panel-title">
          <div>
            <h2>Totals by bank</h2>
            <span>Credits, debits and net cashflow per bank account. Exact duplicates are excluded.</span>
          </div>
        </div>
        <DataTable rows={dashboard.bank_totals} columns={bankTotalsColumns} empty="No bank movements in this period." />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Bank tabs</h2>
          <span>Expenses, deposit confirmation and all transactions</span>
        </div>
        <div className="preset-tabs" aria-label="Bank views">
          <button className={`date-preset ${activeTab === "transactions" ? "active" : ""}`} onClick={() => setActiveTab("transactions")}>
            All transactions
          </button>
          <button className={`date-preset ${activeTab === "expenses" ? "active" : ""}`} onClick={() => setActiveTab("expenses")}>
            Expense analysis
          </button>
          <button className={`date-preset ${activeTab === "deposits" ? "active" : ""}`} onClick={() => setActiveTab("deposits")}>
            Deposit confirmation
          </button>
        </div>
      </section>

      {activeTab === "expenses" ? (
        <section className="panel">
          <div className="panel-title">
            <h2>Expense analysis</h2>
            <span>Where money goes based on bank transaction text.</span>
          </div>
          <DataTable rows={dashboard.expense_categories} columns={expenseColumns} empty="No expenses in this period." />
        </section>
      ) : null}

      {activeTab === "deposits" ? (
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>Deposit confirmation</h2>
              <span>Export this list for the team that releases paid orders.</span>
            </div>
            <button
              className="secondary-action compact"
              onClick={() =>
                downloadExcel(
                  `bank-deposit-confirmations-${dateFrom}-${dateTo}.xls`,
                  [
                    "Date",
                    "Bank",
                    "Amount",
                    "Payer",
                    "Description",
                    "Reference",
                    "Order",
                    "Payment covers",
                    "Order total",
                    "Matched bank total",
                    "Products",
                    "Shipping",
                    "Gap",
                    "Related payments",
                    "Match",
                    "Review reason"
                  ],
                  depositExportRows(dashboard.deposits)
                )
              }
              disabled={dashboard.deposits.length === 0}
            >
              <Download size={17} />
              Export Excel
            </button>
          </div>
          <DataTable rows={dashboard.deposits} columns={depositColumns} empty="No deposits in this period." />
        </section>
      ) : null}

      {activeTab === "transactions" ? (
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>All bank transactions</h2>
              <span>Every imported bank movement, one by one.</span>
            </div>
            <button
              className="secondary-action compact"
              onClick={() =>
                downloadExcel(
                  `bank-transactions-${dateFrom}-${dateTo}.xls`,
                  [
                    "Date",
                    "Value date",
                    "Bank",
                    "Account",
                    "Type",
                    "Category",
                    "Description",
                    "Counterparty",
                    "Reference",
                    "Debit",
                    "Credit",
                    "Balance",
                    "Source file"
                  ],
                  transactionExportRows(dashboard.transactions)
                )
              }
              disabled={dashboard.transactions.length === 0}
            >
              <Download size={17} />
              Export Excel
            </button>
          </div>
          <DataTable rows={dashboard.transactions} columns={transactionColumns} empty="No bank transactions imported for this period." />
        </section>
      ) : null}
    </div>
  );
}
