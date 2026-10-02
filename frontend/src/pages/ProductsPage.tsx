import { useEffect, useMemo, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("el-GR", { style: "percent", maximumFractionDigits: 2 });

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
  net_sales: number | null;
  cogs: number | null;
  gross_profit: number | null;
  margin_percent: number | null;
  cost_coverage_percent: number;
  current_unit_cogs: number | null;
  cogs_source: string | null;
  cogs_date: string | null;
  cogs_confidence: number | null;
  cost_provenance: Array<{ source: string; reference: string | null; date: string; unit_cost: number; confidence: number }>;
  average_unit_price: number;
  average_quantity_per_order: number;
  last_sold_at: string | null;
  catalog_status: string | null;
  catalog_quantity: number | null;
  catalog_price: number | null;
  image_url: string | null;
  link: string | null;
};

type SortDirection = "asc" | "desc";
type SortKey =
  | "product"
  | "brand"
  | "category"
  | "quantity"
  | "orders"
  | "average_quantity_per_order"
  | "revenue"
  | "cogs"
  | "gross_profit"
  | "margin_percent"
  | "average_unit_price"
  | "feed";

type SortState = {
  key: SortKey;
  direction: SortDirection;
};

function textValue(value: string | null | undefined) {
  return value?.trim() || "";
}

function compareText(a: string | null | undefined, b: string | null | undefined) {
  return textValue(a).localeCompare(textValue(b), "el", { sensitivity: "base", numeric: true });
}

function compareNumber(a: number | null | undefined, b: number | null | undefined) {
  return (a ?? 0) - (b ?? 0);
}

export function ProductsPage() {
  const today = isoDate();
  const [dateTo, setDateTo] = useState(today);
  const [dateFrom, setDateFrom] = useState(isoDate(-30));
  const [rows, setRows] = useState<ProductRow[]>([]);
  const [sort, setSort] = useState<SortState>({ key: "revenue", direction: "desc" });
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

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current.key === key ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: "desc" }
    );
  }

  useEffect(() => {
    load();
  }, []);

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      let result = 0;
      switch (sort.key) {
        case "product":
          result = compareText(a.name, b.name);
          break;
        case "brand":
          result = compareText(a.brand, b.brand);
          break;
        case "category":
          result = compareText(a.category, b.category);
          break;
        case "quantity":
          result = compareNumber(a.quantity, b.quantity);
          break;
        case "orders":
          result = compareNumber(a.orders, b.orders);
          break;
        case "average_quantity_per_order":
          result = compareNumber(a.average_quantity_per_order, b.average_quantity_per_order);
          break;
        case "revenue":
          result = compareNumber(a.net_sales, b.net_sales);
          break;
        case "cogs":
          result = compareNumber(a.cogs, b.cogs);
          break;
        case "gross_profit":
          result = compareNumber(a.gross_profit, b.gross_profit);
          break;
        case "margin_percent":
          result = compareNumber(a.margin_percent, b.margin_percent);
          break;
        case "average_unit_price":
          result = compareNumber(a.average_unit_price, b.average_unit_price);
          break;
        case "feed":
          result =
            compareText(a.catalog_status, b.catalog_status) ||
            compareNumber(a.catalog_quantity, b.catalog_quantity) ||
            compareText(a.name, b.name);
          break;
      }
      return sort.direction === "asc" ? result : -result;
    });
  }, [rows, sort]);

  const sortDirection = (key: SortKey) => (sort.key === key ? sort.direction : null);

  const columns: Column<ProductRow>[] = useMemo(
    () => [
      {
        key: "product",
        header: "Product",
        sortable: true,
        sortDirection: sortDirection("product"),
        onSort: () => toggleSort("product"),
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
      {
        key: "brand",
        header: "Brand",
        sortable: true,
        sortDirection: sortDirection("brand"),
        onSort: () => toggleSort("brand"),
        render: (row) => row.brand
      },
      {
        key: "category",
        header: "Category",
        sortable: true,
        sortDirection: sortDirection("category"),
        onSort: () => toggleSort("category"),
        render: (row) => row.category
      },
      {
        key: "qty",
        header: "Qty",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("quantity"),
        onSort: () => toggleSort("quantity"),
        render: (row) => number.format(row.quantity)
      },
      {
        key: "orders",
        header: "Orders",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("orders"),
        onSort: () => toggleSort("orders"),
        render: (row) => number.format(row.orders)
      },
      {
        key: "qpo",
        header: "Qty/order",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("average_quantity_per_order"),
        onSort: () => toggleSort("average_quantity_per_order"),
        render: (row) => number.format(row.average_quantity_per_order)
      },
      {
        key: "revenue",
        header: "Net sales",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("revenue"),
        onSort: () => toggleSort("revenue"),
        render: (row) => row.net_sales === null ? "Unknown" : currency.format(row.net_sales)
      },
      {
        key: "cogs",
        header: "COGS",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("cogs"),
        onSort: () => toggleSort("cogs"),
        render: (row) => (row.cogs === null ? "-" : currency.format(row.cogs))
      },
      {
        key: "gross-profit",
        header: "Gross profit",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("gross_profit"),
        onSort: () => toggleSort("gross_profit"),
        render: (row) => (row.gross_profit === null ? "-" : currency.format(row.gross_profit))
      },
      {
        key: "margin",
        header: "Margin",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("margin_percent"),
        onSort: () => toggleSort("margin_percent"),
        render: (row) => (row.margin_percent === null ? "-" : percent.format(row.margin_percent / 100))
      },
      {
        key: "cogs-source",
        header: "COGS source",
        render: (row) => (
          <div className="stacked-cell">
            <span>{row.cogs_source || "Unknown"}</span>
            <small>{row.cogs_confidence === null ? "-" : percent.format(row.cogs_confidence)} confidence · {number.format(row.cost_coverage_percent)}% coverage</small>
            {row.cost_provenance?.length ? <details><summary>Sources</summary>{row.cost_provenance.map((source, index) => <small key={index}>{source.date} · {source.reference || source.source} · {currency.format(source.unit_cost)}</small>)}</details> : null}
            <small>{row.cogs_date || `${number.format(row.cost_coverage_percent)}% coverage`}</small>
          </div>
        )
      },
      {
        key: "avg",
        header: "Avg.",
        align: "right",
        sortable: true,
        sortDirection: sortDirection("average_unit_price"),
        onSort: () => toggleSort("average_unit_price"),
        render: (row) => currency.format(row.average_unit_price)
      },
      {
        key: "stock",
        header: "Feed",
        sortable: true,
        sortDirection: sortDirection("feed"),
        onSort: () => toggleSort("feed"),
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
    [sort]
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
        <DataTable rows={sortedRows} columns={columns} empty="No product sales for this period." />
      </section>
    </div>
  );
}
