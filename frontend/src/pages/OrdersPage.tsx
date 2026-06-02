import { useEffect, useMemo, useState } from "react";
import { Download, PackageCheck, RefreshCw, ShoppingCart, Truck, WalletCards } from "lucide-react";
import { api } from "../api/client";
import type { OrderRow, OrdersOverview, SupplierProductSale, SupplierSale } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import "../styles/date-presets.css";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

type OrdersTab = "orders" | "suppliers";

const emptyOverview: OrdersOverview = {
  summary: {
    orders: 0,
    paid_orders: 0,
    partial_orders: 0,
    unpaid_orders: 0,
    overpaid_orders: 0,
    products_total: 0,
    shipping_total: 0,
    order_total: 0,
    paid_amount: 0,
    balance_due: 0,
    product_quantity: 0,
    suppliers: 0
  },
  orders: [],
  supplier_sales: [],
  supplier_products: []
};

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
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

function paymentDetails(row: OrderRow) {
  if (row.payments.length === 0) {
    return "-";
  }
  return row.payments
    .map((payment) => `${payment.transaction_date} ${payment.bank_name} ${currency.format(payment.amount)}`)
    .join(" | ");
}

function orderExportRows(rows: OrderRow[]) {
  return rows.map((row) => [
    row.date_added.slice(0, 10),
    row.order_id,
    row.order_status || "",
    row.payment_status,
    row.products_total,
    row.shipping_total,
    row.tax_total,
    row.order_total,
    row.paid_amount,
    row.balance_due,
    row.product_quantity,
    row.payment_method || "",
    row.shipping_method || "",
    paymentDetails(row)
  ]);
}

function supplierExportRows(rows: SupplierSale[]) {
  return rows.map((row) => [row.supplier, row.orders, row.product_lines, row.quantity, row.revenue]);
}

function supplierProductExportRows(rows: SupplierProductSale[]) {
  return rows.map((row) => [
    row.supplier,
    row.product_name,
    row.sku || "",
    row.model || "",
    row.product_id || "",
    row.orders,
    row.quantity,
    row.revenue
  ]);
}

export function OrdersPage() {
  const [dateFrom, setDateFrom] = useState(isoDate(-29));
  const [dateTo, setDateTo] = useState(isoDate());
  const [activeTab, setActiveTab] = useState<OrdersTab>("orders");
  const [overview, setOverview] = useState<OrdersOverview>(emptyOverview);
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load(nextFrom = dateFrom, nextTo = dateTo) {
    setLoading(true);
    setError("");
    try {
      const result = await api.ordersOverview(nextFrom, nextTo);
      setOverview(result.data ?? emptyOverview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load orders");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const visibleOrders = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return overview.orders.filter((row) => {
      if (statusFilter !== "all" && row.payment_status !== statusFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return [row.order_id, row.order_status, row.payment_method, row.shipping_method, paymentDetails(row)]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [overview.orders, search, statusFilter]);

  const orderColumns: Column<OrderRow>[] = useMemo(
    () => [
      { key: "date", header: "Date", render: (row) => row.date_added.slice(0, 10) },
      { key: "order", header: "Order", render: (row) => <strong>{row.order_id}</strong> },
      { key: "status", header: "Status", render: (row) => row.order_status || "-" },
      { key: "payment_status", header: "Paid?", render: (row) => <StatusBadge value={row.payment_status} /> },
      { key: "products", header: "Products", align: "right", render: (row) => currency.format(row.products_total) },
      { key: "shipping", header: "Shipping", align: "right", render: (row) => currency.format(row.shipping_total) },
      { key: "total", header: "Total", align: "right", render: (row) => currency.format(row.order_total) },
      { key: "paid", header: "Paid", align: "right", render: (row) => currency.format(row.paid_amount) },
      { key: "balance", header: "Balance", align: "right", render: (row) => currency.format(row.balance_due) },
      { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.product_quantity) },
      {
        key: "methods",
        header: "Methods",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.payment_method || "-"}</strong>
            <span>{row.shipping_method || "-"}</span>
          </div>
        )
      },
      {
        key: "payments",
        header: "Bank payments",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.payments.length ? `${number.format(row.payments.length)} payment rows` : "-"}</strong>
            <span>{paymentDetails(row)}</span>
          </div>
        )
      }
    ],
    []
  );

  const supplierColumns: Column<SupplierSale>[] = useMemo(
    () => [
      { key: "supplier", header: "Supplier", render: (row) => <strong>{row.supplier}</strong> },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "lines", header: "Product lines", align: "right", render: (row) => number.format(row.product_lines) },
      { key: "qty", header: "Qty sold", align: "right", render: (row) => number.format(row.quantity) },
      { key: "revenue", header: "Product revenue", align: "right", render: (row) => currency.format(row.revenue) }
    ],
    []
  );

  const productColumns: Column<SupplierProductSale>[] = useMemo(
    () => [
      { key: "supplier", header: "Supplier", render: (row) => row.supplier },
      {
        key: "product",
        header: "Product",
        render: (row) => (
          <div className="audit-title-cell">
            <strong>{row.product_name}</strong>
            <span>{[row.sku, row.model, row.product_id].filter(Boolean).join(" | ") || "-"}</span>
          </div>
        )
      },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "qty", header: "Qty sold", align: "right", render: (row) => number.format(row.quantity) },
      { key: "revenue", header: "Product revenue", align: "right", render: (row) => currency.format(row.revenue) }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Orders</h1>
          <p>OpenCart orders with bank payment status, shipping totals and product sales by supplier.</p>
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

      {error ? <div className="notice error">{error}</div> : null}

      <section className="stats-grid">
        <StatCard label="Orders" value={number.format(overview.summary.orders)} detail={`${number.format(overview.summary.product_quantity)} products sold`} icon={ShoppingCart} />
        <StatCard label="Paid orders" value={number.format(overview.summary.paid_orders)} detail={`${number.format(overview.summary.partial_orders)} partial, ${number.format(overview.summary.unpaid_orders)} unpaid`} icon={WalletCards} />
        <StatCard label="Products total" value={currency.format(overview.summary.products_total)} detail="OpenCart product subtotal" icon={PackageCheck} />
        <StatCard label="Shipping total" value={currency.format(overview.summary.shipping_total)} detail="OpenCart shipping revenue" icon={Truck} />
        <StatCard label="Balance due" value={currency.format(overview.summary.balance_due)} detail={`${currency.format(overview.summary.paid_amount)} matched in bank`} icon={WalletCards} />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h2>Order views</h2>
          <span>{loading ? "Loading..." : `${number.format(visibleOrders.length)} visible orders`}</span>
        </div>
        <div className="preset-tabs" aria-label="Order views">
          <button className={`date-preset ${activeTab === "orders" ? "active" : ""}`} onClick={() => setActiveTab("orders")}>
            Orders
          </button>
          <button className={`date-preset ${activeTab === "suppliers" ? "active" : ""}`} onClick={() => setActiveTab("suppliers")}>
            Suppliers
          </button>
        </div>
      </section>

      {activeTab === "orders" ? (
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>Paid and unpaid orders</h2>
              <span>Payment status comes from matched bank deposits.</span>
            </div>
            <button
              className="secondary-action compact"
              onClick={() =>
                downloadExcel(
                  `orders-payment-status-${dateFrom}-${dateTo}.xls`,
                  [
                    "Date",
                    "Order",
                    "Order status",
                    "Payment status",
                    "Products",
                    "Shipping",
                    "Tax",
                    "Total",
                    "Paid",
                    "Balance due",
                    "Qty",
                    "Payment method",
                    "Shipping method",
                    "Bank payments"
                  ],
                  orderExportRows(visibleOrders)
                )
              }
              disabled={visibleOrders.length === 0}
            >
              <Download size={17} />
              Export Excel
            </button>
          </div>
          <div className="sync-controls">
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">All payment statuses</option>
              <option value="paid">Paid</option>
              <option value="partial">Partial</option>
              <option value="unpaid">Unpaid</option>
              <option value="overpaid">Overpaid</option>
            </select>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Order, status, payment method..." />
          </div>
          <DataTable rows={visibleOrders} columns={orderColumns} empty="No OpenCart orders in this period." />
        </section>
      ) : null}

      {activeTab === "suppliers" ? (
        <>
          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Product sales by supplier</h2>
                <span>{number.format(overview.summary.suppliers)} suppliers found from OpenCart order lines.</span>
              </div>
              <button
                className="secondary-action compact"
                onClick={() =>
                  downloadExcel(
                    `supplier-sales-${dateFrom}-${dateTo}.xls`,
                    ["Supplier", "Orders", "Product lines", "Qty sold", "Product revenue"],
                    supplierExportRows(overview.supplier_sales)
                  )
                }
                disabled={overview.supplier_sales.length === 0}
              >
                <Download size={17} />
                Export Excel
              </button>
            </div>
            <DataTable rows={overview.supplier_sales} columns={supplierColumns} empty="No product supplier data in this period." />
          </section>

          <section className="panel">
            <div className="panel-title">
              <div>
                <h2>Products per supplier</h2>
                <span>Top 250 product rows by product revenue.</span>
              </div>
              <button
                className="secondary-action compact"
                onClick={() =>
                  downloadExcel(
                    `supplier-product-sales-${dateFrom}-${dateTo}.xls`,
                    ["Supplier", "Product", "SKU", "Model", "Product ID", "Orders", "Qty sold", "Product revenue"],
                    supplierProductExportRows(overview.supplier_products)
                  )
                }
                disabled={overview.supplier_products.length === 0}
              >
                <Download size={17} />
                Export Excel
              </button>
            </div>
            <DataTable rows={overview.supplier_products} columns={productColumns} empty="No product rows in this period." />
          </section>
        </>
      ) : null}
    </div>
  );
}
