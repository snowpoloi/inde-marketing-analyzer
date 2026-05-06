import { useEffect, useMemo, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

type ProductRow = {
  product_id: string | null;
  sku: string | null;
  model: string | null;
  name: string;
  brand: string;
  category: string;
  quantity: number;
  orders: number;
  revenue: number;
  average_unit_price: number;
  last_sold_at: string | null;
  catalog_status: string | null;
  catalog_quantity: number | null;
  catalog_price: number | null;
  image_url: string | null;
  link: string | null;
};

export function ProductsPage() {
  const today = isoDate();
  const [dateTo, setDateTo] = useState(today);
  const [dateFrom, setDateFrom] = useState(isoDate(-30));
  const [rows, setRows] = useState<ProductRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = await api.dashboard("products", dateFrom, dateTo);
      setRows(result.data.rows ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load products");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const columns: Column<ProductRow>[] = useMemo(
    () => [
      {
        key: "product",
        header: "Product",
        render: (row) => (
          <div className="product-cell">
            {row.image_url ? <img src={row.image_url} alt="" loading="lazy" /> : <span className="product-thumb" />}
            <div>
              <strong>{row.name}</strong>
              <span>{row.sku || row.model || row.product_id || "-"}</span>
            </div>
          </div>
        )
      },
      { key: "brand", header: "Brand", render: (row) => row.brand },
      { key: "category", header: "Category", render: (row) => row.category },
      { key: "qty", header: "Qty", align: "right", render: (row) => number.format(row.quantity) },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "revenue", header: "Revenue", align: "right", render: (row) => currency.format(row.revenue) },
      { key: "avg", header: "Avg.", align: "right", render: (row) => currency.format(row.average_unit_price) },
      {
        key: "stock",
        header: "Feed",
        render: (row) =>
          row.catalog_status ? (
            <div className="feed-status">
              <StatusBadge value={row.catalog_status} />
              <span>{row.catalog_quantity === null ? "-" : `${number.format(row.catalog_quantity)} stock`}</span>
            </div>
          ) : (
            "-"
          )
      },
      {
        key: "link",
        header: "",
        align: "center",
        render: (row) =>
          row.link ? (
            <a className="icon-link" href={row.link} target="_blank" rel="noreferrer" aria-label="Open product">
              <ExternalLink size={16} />
            </a>
          ) : null
      }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Products</h1>
          <p>Best-selling products from OpenCart sales enriched with the XML product feed.</p>
        </div>
        <div className="date-controls">
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <button className="primary-action compact" onClick={load} disabled={loading}>
            <RefreshCw size={17} />
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="notice error">{error}</div> : null}

      <section className="panel">
        <div className="panel-title">
          <h2>Product sales</h2>
          <span>{loading ? "Loading" : `${number.format(rows.length)} products`}</span>
        </div>
        <DataTable rows={rows} columns={columns} empty="No product sales for this period." />
      </section>
    </div>
  );
}
