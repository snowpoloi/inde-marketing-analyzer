import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Check,
  CircleDollarSign,
  Download,
  PackageSearch,
  RefreshCw,
  Truck,
  Upload,
  History, Search, Save, X, Calculator
} from "lucide-react";
import {
  api,
  type SupplierPerformance,
  type SupplierProduct,
  type SupplierSummary,
  type UnmatchedSupplierProduct,
  type SupplierMatchCandidate, type SupplierCostHistory
} from "../api/client";
import { DataTable, type Column } from "../components/DataTable";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { SupplierGmailPanel } from "../components/SupplierGmailPanel";
import { SupplierAADEPanel } from "../components/SupplierAADEPanel";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2, style: "percent" });

type Tab = "products" | "unmatched" | "performance" | "import" | "gmail" | "aade";

function isoDate(offset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offset);
  return value.toISOString().slice(0, 10);
}

function downloadTemplate() {
  const template = {
    supplier: {
      code: "MEGAPAP",
      name: "MEGAPAP",
      vat_number: null,
      default_currency: "EUR"
    },
    source_type: "json",
    source_reference: "supplier-export",
    documents: [
      {
        document_type: "invoice",
        document_number: "INV-001",
        document_date: isoDate(),
        supplier_order_id: "ORDER-001",
        currency: "EUR",
        lines: [
          {
            line_number: "1",
            line_type: "product",
            supplier_code: "0212605",
            supplier_sku: "GP041-0025,4",
            supplier_ean: null,
            description: "Product description",
            quantity: 1,
            unit_price_before_discount: 8.73,
            discount_percent: 0,
            vat_rate: 24,
            vat_amount: 2.0952,
            gross_total: 10.8252
          },
          {
            line_number: "2",
            line_type: "shipping",
            description: "Supplier shipping",
            quantity: 1,
            net_line_total: 4.9,
            vat_rate: 24,
            vat_amount: 1.176,
            gross_total: 6.076,
            shipping_type: "INBOUND"
          }
        ]
      }
    ]
  };
  const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "supplier-import-template.json";
  link.click();
  URL.revokeObjectURL(url);
}

export function SuppliersPage({onSettings}: {onSettings:()=>void}) {
  const [dateFrom, setDateFrom] = useState(isoDate(-30));
  const [dateTo, setDateTo] = useState(isoDate());
  const [tab, setTab] = useState<Tab>("products");
  const [summary, setSummary] = useState<SupplierSummary | null>(null);
  const [products, setProducts] = useState<SupplierProduct[]>([]);
  const [unmatched, setUnmatched] = useState<UnmatchedSupplierProduct[]>([]);
  const [performance, setPerformance] = useState<SupplierPerformance[]>([]);
  const [selectedCandidates, setSelectedCandidates] = useState<Record<string, string>>({});
  const [conversionFactors, setConversionFactors] = useState<Record<string, number>>({});
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [searchQueries, setSearchQueries] = useState<Record<string, string>>({});
  const [searchResults, setSearchResults] = useState<Record<string, SupplierMatchCandidate[]>>({});
  const [historyProduct, setHistoryProduct] = useState<SupplierProduct | null>(null);
  const [history, setHistory] = useState<SupplierCostHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [manualDate, setManualDate] = useState(isoDate());
  const [manualPrice, setManualPrice] = useState("");
  const [manualReference, setManualReference] = useState("");
  const [thresholds, setThresholds] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const [simulations, setSimulations] = useState<Record<string, { eligible_orders: number; orders: number; potential_savings: number; additional_purchase_to_threshold: number }>>({});
  const fileInput = useRef<HTMLInputElement>(null);
  const savingRef = useRef(saving);
  savingRef.current = saving;
  useEffect(() => {
    if (!historyProduct) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>(".supplier-modal");
    dialog?.querySelector<HTMLElement>("button")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !savingRef.current) { setHistoryProduct(null); return; }
      if (event.key !== "Tab" || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary'));
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; previous?.focus(); };
  }, [historyProduct?.mapping_id]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [summaryResult, productsResult, unmatchedResult, performanceResult] = await Promise.all([
        api.supplierSummary(dateFrom, dateTo),
        api.supplierProducts(dateTo),
        api.unmatchedSupplierProducts(),
        api.supplierPerformance(dateFrom, dateTo)
      ]);
      setSummary(summaryResult.data);
      setProducts(productsResult.data.rows);
      setUnmatched(unmatchedResult.data.rows);
      setPerformance(performanceResult.data.rows);
      setSimulations({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load supplier data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function verify(row: UnmatchedSupplierProduct) {
    const productCatalogId = selectedCandidates[row.mapping_id];
    if (!productCatalogId) {
      setError("Select an OpenCart product before verifying the mapping.");
      return;
    }
    const factor = conversionFactors[row.mapping_id] ?? 1;
    if (!Number.isFinite(factor) || factor <= 0) { setError("Units per pack must be positive."); return; }
    setSaving(row.mapping_id);
    setError("");
    setNotice("");
    try {
      const result = await api.verifySupplierMapping(row.mapping_id, {
        product_catalog_id: productCatalogId,
        conversion_factor: factor,
        pack_quantity: factor
      });
      setNotice(`Mapping verified. ${result.data.costs_created} historical cost rows created.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not verify mapping");
    } finally {
      setSaving("");
    }
  }

  async function searchCatalog(row: UnmatchedSupplierProduct) {
    const query = searchQueries[row.mapping_id] || "";
    if (query.trim().length < 2) return;
    setSaving(`search:${row.mapping_id}`);
    setError("");
    try {
      const result = await api.supplierCatalogSearch(query);
      setSearchResults((current) => ({ ...current, [row.mapping_id]: result.data.rows }));
    } catch (err) { setError(err instanceof Error ? err.message : "Search failed"); }
    finally { setSaving(""); }
  }

  async function openHistory(row: SupplierProduct) {
    setHistoryProduct(row); setHistory([]); setHistoryLoading(true); setError("");
    setManualPrice(""); setManualReference("");
    try { setHistory((await api.supplierCostHistory(row.mapping_id)).data.rows); }
    catch (err) { setError(err instanceof Error ? err.message : "History failed"); }
    finally { setHistoryLoading(false); }
  }

  async function saveManualCost() {
    if (!historyProduct || !manualPrice || !manualReference.trim() || !manualDate || Number(manualPrice) < 0 || !Number.isFinite(Number(manualPrice))) {
      setError("Enter a valid price, date and source reference."); return;
    }
    setSaving("manual"); setError("");
    try {
      await api.addManualSupplierCost({ supplier_id: historyProduct.supplier_id, supplier_product_map_id: historyProduct.mapping_id,
        purchase_date: manualDate, net_unit_cost: Number(manualPrice), source_reference: manualReference.trim() });
      setHistory((await api.supplierCostHistory(historyProduct.mapping_id)).data.rows);
      setManualPrice(""); setManualReference(""); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Cost could not be saved"); }
    finally { setSaving(""); }
  }

  async function saveThreshold(row: SupplierPerformance) {
    const value = thresholds[row.supplier_id] ?? String(row.free_shipping_threshold ?? "");
    if (value !== "" && (!Number.isFinite(Number(value)) || Number(value) < 0)) { setError("Threshold must be positive or empty."); return; }
    setSaving(row.supplier_id); setError("");
    try { await api.saveSupplierThreshold(row.supplier_id, value === "" ? null : Number(value)); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Threshold could not be saved"); }
    finally { setSaving(""); }
  }

  async function simulateThreshold(row: SupplierPerformance) {
    const value = thresholds[row.supplier_id] ?? String(row.free_shipping_threshold ?? "");
    if (value === "" || !Number.isFinite(Number(value)) || Number(value) < 0) { setError("Enter a threshold for the simulation."); return; }
    setSaving(`simulate:${row.supplier_id}`); setError("");
    try { const result = await api.supplierShippingSimulation(row.supplier_id, Number(value), dateFrom, dateTo); setSimulations((current) => ({ ...current, [row.supplier_id]: result.data })); }
    catch (err) { setError(err instanceof Error ? err.message : "Simulation failed"); }
    finally { setSaving(""); }
  }

  async function importJson() {
    if (!file) {
      setError("Choose a supplier JSON file first.");
      return;
    }
    setSaving("import");
    setError("");
    setNotice("");
    try {
      const result = await api.importSupplierJson(file);
      const data = result.data;
      setNotice(
        data.duplicate
          ? "This exact import was already processed. No duplicate costs were added."
          : `${data.documents_imported} documents imported, ${data.matched_lines} matched and ${data.unmatched_lines} sent to review.`
      );
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not import supplier file");
    } finally {
      setSaving("");
    }
  }

  const productColumns: Column<SupplierProduct>[] = useMemo(
    () => [
      { key: "supplier", header: "Supplier", render: (row) => <strong>{row.supplier}</strong> },
      {
        key: "supplier-id",
        header: "Supplier product",
        render: (row) => (
          <div className="stacked-cell">
            <strong>{row.supplier_sku || "-"}</strong>
            <span>{row.supplier_code || row.supplier_ean || "-"}</span>
          </div>
        )
      },
      {
        key: "opencart",
        header: "OpenCart product",
        render: (row) => (
          <div className="stacked-cell">
            <strong>{row.product_name || "Unmatched"}</strong>
            <span>{row.opencart_sku || row.opencart_model || row.opencart_product_id || "-"}</span>
          </div>
        )
      },
      { key: "current", header: "Current COGS", align: "right", render: (row) => (row.current_cogs === null ? "-" : currency.format(row.current_cogs)) },
      { key: "previous", header: "Previous COGS", align: "right", render: (row) => (row.previous_cogs === null ? "-" : currency.format(row.previous_cogs)) },
      {
        key: "change",
        header: "Change",
        align: "right",
        render: (row) =>
          row.cost_change_percent === null ? (
            "-"
          ) : (
            <span className={row.cost_change_percent > 0 ? "metric-up" : "metric-down"}>
              {row.cost_change_percent > 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
              {percent.format(row.cost_change_percent / 100)}
            </span>
          )
      },
      {
        key: "source",
        header: "Source",
        render: (row) => (
          <div className="stacked-cell">
            <span>{row.cost_source || "Unknown"}</span>
            <small>{row.cost_date || "-"} | {row.cost_confidence === null ? "-" : percent.format(row.cost_confidence)}</small>
            <small title={row.cost_reference || ""}>{row.cost_reference || "-"}</small>
          </div>
        )
      },
      { key: "status", header: "Match", render: (row) => <div className="stacked-cell"><StatusBadge value={row.verified ? "verified" : row.match_status} /><small>{percent.format(row.match_confidence)}</small></div> },
      { key: "history", header: "", render: (row) => <button className="icon-button" title="Cost history" aria-label={`Cost history ${row.product_name}`} onClick={() => openHistory(row)}><History size={17} /></button> }
    ],
    []
  );

  const unmatchedColumns: Column<UnmatchedSupplierProduct>[] = useMemo(
    () => [
      { key: "supplier", header: "Supplier", render: (row) => <strong>{row.supplier}</strong> },
      {
        key: "identifier",
        header: "Supplier identifier",
        render: (row) => (
          <div className="stacked-cell">
            <strong>{row.supplier_sku || row.supplier_code || "-"}</strong>
            <span>{row.supplier_ean || "-"}</span>
          </div>
        )
      },
      { key: "description", header: "Description", render: (row) => row.description || "-" },
      { key: "evidence", header: "Document / cost", render: (row) => <div className="stacked-cell">{row.documents?.map((doc, index) => <span key={index}>{doc.number || "-"} | {doc.date} | {currency.format(doc.purchase_cost)}</span>)}</div> },
      { key: "reason", header: "Review reason", render: (row) => row.reason || "No verified mapping" },
      {
        key: "candidate",
        header: "OpenCart candidate",
        render: (row) => {
          const candidates = [...new Map([...row.candidates, ...(searchResults[row.mapping_id] || [])].map((candidate) => [candidate.product_catalog_id, candidate])).values()];
          return <div className="supplier-candidate">
            <div className="supplier-search"><input aria-label={`Search catalog ${row.supplier_sku || row.supplier_code}`} placeholder="SKU, model or product name" value={searchQueries[row.mapping_id] || ""} onChange={(event) => setSearchQueries((current) => ({ ...current, [row.mapping_id]: event.target.value }))} /><button className="icon-button" title="Search catalog" onClick={() => searchCatalog(row)} disabled={Boolean(saving)}><Search size={16} /></button></div>
            <select
              aria-label={`Select product ${row.supplier_sku || row.supplier_code}`}
              value={selectedCandidates[row.mapping_id] || ""}
              onChange={(event) =>
                setSelectedCandidates((current) => ({ ...current, [row.mapping_id]: event.target.value }))
              }
            >
              <option value="">Select product</option>
              {candidates.map((candidate) => (
                <option key={candidate.product_catalog_id} value={candidate.product_catalog_id}>
                  {candidate.name} | {candidate.sku || candidate.model || candidate.product_id || "-"} | {number.format(candidate.confidence * 100)}%
                </option>
              ))}
            </select>
          </div>;
        }
      },
      {
        key: "factor",
        header: "Units/pack",
        align: "right",
        render: (row) => (
          <input
            className="compact-number"
            type="number"
            min="0.0001"
            step="0.0001"
            aria-label={`Units per pack ${row.supplier_sku || row.supplier_code}`}
            value={conversionFactors[row.mapping_id] ?? 1}
            onChange={(event) =>
              setConversionFactors((current) => ({ ...current, [row.mapping_id]: Number(event.target.value) }))
            }
          />
        )
      },
      {
        key: "verify",
        header: "",
        align: "right",
        render: (row) => (
          <button
            className="primary-action compact"
            onClick={() => verify(row)}
            disabled={!selectedCandidates[row.mapping_id] || Boolean(saving)}
          >
            <Check size={16} />
            Verify
          </button>
        )
      }
    ],
    [conversionFactors, saving, selectedCandidates, searchQueries, searchResults]
  );

  const performanceColumns: Column<SupplierPerformance>[] = useMemo(
    () => [
      { key: "supplier", header: "Supplier", render: (row) => <strong>{row.supplier}</strong> },
      { key: "purchases", header: "Purchases", align: "right", render: (row) => currency.format(row.purchases) },
      { key: "freight", header: "Freight", align: "right", render: (row) => currency.format(row.freight) },
      { key: "ratio", header: "Freight / purchases", align: "right", render: (row) => percent.format(row.freight_ratio / 100) },
      { key: "orders", header: "Orders", align: "right", render: (row) => number.format(row.orders) },
      { key: "avg-order", header: "Avg. order", align: "right", render: (row) => currency.format(row.average_order) },
      { key: "avg-freight", header: "Avg. freight", align: "right", render: (row) => currency.format(row.average_freight_per_order) },
      {
        key: "shipping-orders",
        header: "Free / paid / unknown",
        align: "right",
        render: (row) => `${number.format(row.free_shipping_orders)} / ${number.format(row.paid_shipping_orders)} / ${number.format(row.unknown_shipping_orders)}`
      },
      { key: "increases", header: "Price increases", align: "right", render: (row) => number.format(row.price_increases) }
    ],
    []
  );

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Suppliers &amp; COGS</h1>
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
      {notice ? <div className="notice success">{notice}</div> : null}

      <div className="stats-grid supplier-stats">
        <StatCard label="Purchases" value={currency.format(summary?.purchases ?? 0)} detail="Invoices less credit notes, net" icon={CircleDollarSign} />
        <StatCard label="Supplier freight" value={currency.format(summary?.freight ?? 0)} detail="Excluded from product COGS" icon={Truck} />
        <StatCard label="Products with COGS" value={number.format(summary?.products_with_cogs ?? 0)} detail={`${number.format(summary?.matched_products ?? 0)} matched`} icon={PackageSearch} />
        <StatCard label="Needs review" value={number.format(summary?.unmatched_products ?? 0)} detail="Pending verification" icon={PackageSearch} />
      </div>

      <div className="view-tabs" role="tablist" aria-label="Supplier views">
        <button className={tab === "products" ? "active" : ""} onClick={() => setTab("products")}>Supplier products</button>
        <button className={tab === "unmatched" ? "active" : ""} onClick={() => setTab("unmatched")}>Unmatched products</button>
        <button className={tab === "performance" ? "active" : ""} onClick={() => setTab("performance")}>Supplier performance</button>
        <button className={tab === "import" ? "active" : ""} onClick={() => setTab("import")}>Import</button>
        <button className={tab === "gmail" ? "active" : ""} onClick={() => setTab("gmail")}>Gmail documents</button>
        <button className={tab === "aade" ? "active" : ""} onClick={() => setTab("aade")}>AADE costs</button>
      </div>

      {tab !== "import" && tab !== "gmail" && tab !== "aade" ? <input className="supplier-filter" aria-label="Filter suppliers and products" placeholder="Supplier, SKU or product" value={filter} onChange={(event) => setFilter(event.target.value)} /> : null}
      {tab === "gmail" && <SupplierGmailPanel onImported={load} />}
      {tab === "aade" && <SupplierAADEPanel start={dateFrom} end={dateTo} onImported={load} onSettings={onSettings} />}

      {tab === "products" ? (
        <section className="panel">
          <div className="panel-title"><h2>Supplier products</h2><span>{loading ? "Loading" : `${number.format(products.length)} mappings`}</span></div>
          <DataTable rows={products.filter((row) => [row.supplier, row.supplier_sku, row.supplier_code, row.product_name].join(" ").toLowerCase().includes(filter.toLowerCase()))} columns={productColumns} empty="No supplier product costs found." />
        </section>
      ) : null}

      {tab === "unmatched" ? (
        <section className="panel">
          <div className="panel-title"><h2>Mapping review</h2><span>{number.format(unmatched.length)} unresolved</span></div>
          <DataTable rows={unmatched.filter((row) => [row.supplier, row.supplier_sku, row.description].join(" ").toLowerCase().includes(filter.toLowerCase()))} columns={unmatchedColumns} empty="No unresolved products found." />
        </section>
      ) : null}

      {tab === "performance" ? (
        <section className="panel">
          <div className="panel-title"><h2>Supplier performance</h2><span>{dateFrom} to {dateTo}</span></div>
          <DataTable rows={performance.filter((row) => row.supplier.toLowerCase().includes(filter.toLowerCase()))} columns={performanceColumns} empty="No supplier purchases for this period." />
          {performance.filter((row) => row.supplier.toLowerCase().includes(filter.toLowerCase())).map((row) => <details className="supplier-detail" key={row.supplier_id}>
            <summary>{row.supplier} · Freight &amp; cost changes</summary>
            <div className="supplier-threshold">
              <label>Free-shipping threshold<input type="number" min="0" step="0.01" value={thresholds[row.supplier_id] ?? String(row.free_shipping_threshold ?? "")} onChange={(event) => setThresholds((current) => ({ ...current, [row.supplier_id]: event.target.value }))} /></label>
              <button className="primary-action compact" disabled={Boolean(saving)} onClick={() => saveThreshold(row)}><Save size={16} />Save</button>
              <button className="secondary-action compact" disabled={Boolean(saving)} onClick={() => simulateThreshold(row)}><Calculator size={16} />Simulate</button>
              <span>Gap to threshold: {currency.format(row.threshold_gap)} · Freight above threshold: {currency.format(row.potential_freight_savings)}</span>
            </div>
            {simulations[row.supplier_id] ? <div className="notice">Eligible orders: {simulations[row.supplier_id].eligible_orders} / {simulations[row.supplier_id].orders} · Potential freight savings: {currency.format(simulations[row.supplier_id].potential_savings)} · Additional purchases to threshold: {currency.format(simulations[row.supplier_id].additional_purchase_to_threshold)}</div> : null}
            <DataTable rows={row.shipping_trend} columns={[{ key: "month", header: "Month", render: (item) => item.month }, { key: "freight", header: "Net freight", align: "right", render: (item) => currency.format(item.freight) }]} empty="No freight entries." />
            <DataTable rows={row.shipping_by_type} columns={[{ key: "type", header: "Freight type", render: (item) => item.shipping_type }, { key: "value", header: "Net freight", align: "right", render: (item) => currency.format(item.freight) }]} empty="No freight entries." />
            <DataTable rows={row.margin_erosion_products} columns={[{ key: "product", header: "Product", render: (item) => item.product_name || item.supplier_sku || "-" }, { key: "previous", header: "Previous COGS", align: "right", render: (item) => currency.format(item.previous_cogs) }, { key: "current", header: "Current COGS", align: "right", render: (item) => currency.format(item.current_cogs) }, { key: "increase", header: "Cost increase", align: "right", render: (item) => item.increase_percent === null ? "-" : percent.format(item.increase_percent / 100) }, { key: "erosion", header: "Margin change (points)", align: "right", render: (item) => item.margin_change_points == null ? "-" : number.format(item.margin_change_points) }]} empty="No purchase-cost increases in this period." />
          </details>)}
        </section>
      ) : null}

      {tab === "import" ? (
        <section className="panel supplier-import-panel">
          <div className="panel-title">
            <h2>Import normalized supplier data</h2>
            <button className="secondary-action compact" onClick={downloadTemplate}><Download size={16} />Download template</button>
          </div>
          <div className="supplier-import-controls">
            <input ref={fileInput} aria-label="Supplier JSON file" type="file" accept="application/json,.json" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            <button className="primary-action compact" onClick={importJson} disabled={!file || saving === "import"}>
              <Upload size={16} />Import
            </button>
          </div>
        </section>
      ) : null}

      {historyProduct ? <div className="supplier-modal-backdrop" onClick={() => { if (!saving) setHistoryProduct(null); }}>
        <section className="supplier-modal" role="dialog" aria-modal="true" aria-labelledby="supplier-history-title" onClick={(event) => event.stopPropagation()}>
          <div className="panel-title"><h2 id="supplier-history-title">{historyProduct.product_name || historyProduct.supplier_sku} · Cost history</h2><button className="icon-button" title="Close history" disabled={Boolean(saving)} onClick={() => setHistoryProduct(null)}><X size={18} /></button></div>
          {error ? <div className="notice error">{error}</div> : null}
          <DataTable rows={history} columns={[
            { key: "date", header: "Date", render: (row) => row.date },
            { key: "cost", header: "Net COGS / unit", align: "right", render: (row) => currency.format(row.net_unit_cost) },
            { key: "source", header: "Source", render: (row) => <div className="stacked-cell"><span>{row.source}</span><small>{row.reference || "-"}</small></div> },
            { key: "confidence", header: "Confidence", render: (row) => percent.format(row.confidence) },
            { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> }
          ]} empty={historyLoading ? "Loading history" : "No cost records."} />
          {historyProduct.verified ? <form className="supplier-manual-form" onSubmit={(event) => { event.preventDefault(); saveManualCost(); }}>
            <h3>New manual cost</h3>
            <label>Date<input type="date" required value={manualDate} onChange={(event) => setManualDate(event.target.value)} /></label>
            <label>Net cost / sales unit<input type="number" required min="0" step="0.0001" value={manualPrice} onChange={(event) => setManualPrice(event.target.value)} /></label>
            <label>Source reference<input required value={manualReference} maxLength={500} onChange={(event) => setManualReference(event.target.value)} /></label>
            <button type="submit" className="primary-action compact" disabled={Boolean(saving)}><Save size={16} />Save cost</button>
          </form> : historyProduct.product_catalog_id ? <button className="primary-action compact" disabled={Boolean(saving)} onClick={async () => {
            setSaving("verify-history"); setError("");
            try { await api.verifySupplierMapping(historyProduct.mapping_id, { product_catalog_id: historyProduct.product_catalog_id!, conversion_factor: historyProduct.conversion_factor, pack_quantity: historyProduct.conversion_factor }); setHistoryProduct({ ...historyProduct, verified: true }); await load(); }
            catch (err) { setError(err instanceof Error ? err.message : "Verification failed"); } finally { setSaving(""); }
          }}><Check size={16} />Verify {historyProduct.opencart_sku || historyProduct.opencart_model}</button> : null}
        </section>
      </div> : null}
    </div>
  );
}
