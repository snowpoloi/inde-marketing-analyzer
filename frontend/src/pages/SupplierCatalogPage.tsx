import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, RefreshCw, Search, X } from "lucide-react";
import { api } from "../api/client";
import type { SupplierCatalogFeed, SupplierCatalogPeriod, SupplierCatalogProduct, SupplierCatalogResult } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { SupplierAADEPanel } from "../components/SupplierAADEPanel";

const currency = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const money = (value: number | null) => value == null ? "-" : currency.format(Number(value));
const timestamp = (value: string | null) => value ? new Date(value).toLocaleString("el-GR") : "-";
const percent = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const marginReason = (row: SupplierCatalogProduct) => row.margin_status === "available"
  ? "(Net INDE price - net AADE unit cost) / net INDE price. Excludes freight, ads and other expenses."
  : row.margin_status === "missing_sale_tax_basis" ? "INDE price VAT basis is not confirmed."
  : row.margin_status === "zero_sale_price" ? "Margin percentage is undefined for a zero sale price."
  : "No confirmed AADE purchase unit cost. XML and Gmail prices are not used.";
type Details = Awaited<ReturnType<typeof api.supplierCatalogDetails>>;
const sortKeys: Record<string, string> = { product: "name", code: "supplier_code", sku: "supplier_sku", own: "opencart_sku",
  stock: "quantity", "inde-price": "inde_price", "aade-cost": "aade_cost_net", "unit-profit": "gross_profit_per_unit",
  margin: "gross_margin_percent", wholesale: "wholesale_price_net", retail: "retail_price_gross" };

export function SupplierCatalogPage() {
  const [feeds, setFeeds] = useState<SupplierCatalogFeed[]>([]);
  const [feedId, setFeedId] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [match, setMatch] = useState("all");
  const [availability, setAvailability] = useState("all");
  const [category, setCategory] = useState("");
  const [hasMargin, setHasMargin] = useState(false);
  const [sortBy, setSortBy] = useState("name");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<SupplierCatalogResult | null>(null);
  const [details, setDetails] = useState<Details | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [queuing, setQueuing] = useState(false);
  const [showCosts, setShowCosts] = useState(false);
  const [costSupplier, setCostSupplier] = useState("");
  const [openingCosts, setOpeningCosts] = useState(false);
  const [costStart, setCostStart] = useState(`${new Date().getFullYear()}-01-01`);
  const [costEnd, setCostEnd] = useState(new Date().toISOString().slice(0,10));
  const [period, setPeriod] = useState<SupplierCatalogPeriod | null>(null);
  const [periodLoading, setPeriodLoading] = useState(false);
  const [periodError, setPeriodError] = useState("");
  const periodRequestId = useRef(0);
  const requestId = useRef(0);
  const detailId = useRef(0);
  const selected = feeds.find(feed => feed.id === feedId);
  const active = feeds.some(feed => ["queued", "running"].includes(feed.status));

  async function load() {
    const id = ++requestId.current; setLoading(true);
    try {
      const [rows, data] = await Promise.all([api.supplierCatalogFeeds(), api.supplierCatalogProducts({
        ...(feedId ? { feed_id: feedId } : {}), q: search, match, availability, category, has_margin: String(hasMargin),
        sort_by: sortBy, sort_direction: sortDirection, offset: String(offset), limit: "50"
      })]);
      if (id !== requestId.current) return;
      setFeeds(rows); setResult(data); setError("");
    } catch (err) { if (id === requestId.current) setError(err instanceof Error ? err.message : "Could not load supplier catalog."); }
    finally { if (id === requestId.current) setLoading(false); }
  }
  async function loadPeriod() {
    const id = ++periodRequestId.current;
    if (!costStart || !costEnd || costStart > costEnd) {
      setPeriod(null); setPeriodLoading(false); setPeriodError("Select a valid From / To period."); return;
    }
    setPeriodLoading(true);
    try {
      const data = await api.supplierCatalogPeriod({ date_from: costStart, date_to: costEnd, ...(feedId ? {feed_id: feedId} : {}) });
      if (id === periodRequestId.current) { setPeriod(data); setPeriodError(""); }
    } catch (err) { if (id === periodRequestId.current) { setPeriod(null); setPeriodError(err instanceof Error ? err.message : "Could not load supplier purchases."); } }
    finally { if (id === periodRequestId.current) setPeriodLoading(false); }
  }
  useEffect(() => { load(); return () => { requestId.current++; }; }, [feedId, search, match, availability, category, offset, hasMargin, sortBy, sortDirection]);
  useEffect(() => { loadPeriod(); return () => { periodRequestId.current++; }; }, [feedId, costStart, costEnd]);
  useEffect(() => { if (!active) return; const timer = window.setInterval(load, 10000); return () => window.clearInterval(timer); }, [active, feedId, search, match, availability, category, offset, hasMargin, sortBy, sortDirection]);
  useEffect(() => { const timer = window.setTimeout(() => { setSearch(query); setOffset(0); }, 300); return () => window.clearTimeout(timer); }, [query]);
  useEffect(() => {
    if (!details && !showCosts) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") { detailId.current++; setDetails(null); setShowCosts(false); } };
    window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close);
  }, [details, showCosts]);

  async function sync() {
    if (!feedId) return; setQueuing(true);
    try { await api.syncSupplierCatalog(feedId); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not queue sync."); }
    finally { setQueuing(false); }
  }
  async function inspect(row: SupplierCatalogProduct) {
    const id = ++detailId.current;
    try { const data = await api.supplierCatalogDetails(row.id); if (id === detailId.current) setDetails(data); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load product."); }
  }
  async function openCosts() {
    setOpeningCosts(true);
    try {
      const identities = await api.supplierIdentities();
      setCostSupplier(identities.data.rows.find(row=>row.code === selected?.code)?.id ?? "");
      setShowCosts(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not load supplier identities."); }
    finally { setOpeningCosts(false); }
  }
  const columns: Column<SupplierCatalogProduct>[] = ([
    { key: "product", header: "Supplier product", render: row => <div className="supplier-catalog-product">
      <div className="supplier-catalog-image">{row.image_url && <img src={row.image_url} alt="" loading="lazy" onError={event => { event.currentTarget.style.visibility = "hidden"; }} />}</div>
      <div><strong>{row.name}</strong><small>{row.supplier} · {row.category || "-"}</small></div>
    </div> },
    { key: "code", header: "Supplier model", render: row => row.supplier_code },
    { key: "sku", header: "Supplier SKU / EAN", render: row => <div className="supplier-catalog-stack">{row.supplier_sku || "-"}<small>{row.ean || "-"}</small></div> },
    { key: "own", header: "INDE SKU", render: row => <div className="supplier-catalog-stack">{row.opencart_sku || "-"}<small>{row.match_method === "ambiguous" ? "Needs review" : row.opencart_sku ? "Matched" : "Not matched"}</small></div> },
    { key: "stock", header: "Supplier stock", align: "right", render: row => row.quantity ?? "-" },
    { key: "inde-price", header: "INDE price (VAT incl.)", align: "right", render: row => <div className="supplier-catalog-stack" title={row.inde_price_basis === "unknown" ? "Selling VAT rate not confirmed." : `INDE feed price (${row.inde_price_basis})`}>{money(row.inde_price)}{row.inde_price_net != null && <small>{money(row.inde_price_net)} net</small>}</div> },
    { key: "aade-cost", header: "AADE cost / unit (net)", align: "right", render: row => <div className="supplier-catalog-stack" title={row.aade_mark ? `AADE MARK ${row.aade_mark}` : "No confirmed AADE unit cost"}>{money(row.aade_cost_net)}{row.aade_cost_date && <small>{row.aade_cost_date}</small>}</div> },
    { key: "unit-profit", header: "Gross profit / unit (net)", align: "right", render: row => <span title={marginReason(row)}>{money(row.gross_profit_per_unit)}</span> },
    { key: "margin", header: "Gross margin %", align: "right", render: row => <span title={marginReason(row)}>{row.gross_margin_percent == null ? "-" : `${percent.format(Number(row.gross_margin_percent))}%`}</span> },
    { key: "wholesale", header: "XML wholesale (net)", align: "right", render: row => money(row.wholesale_price_net) },
    { key: "retail", header: "XML retail (gross)", align: "right", render: row => money(row.retail_price_gross) },
    { key: "inspect", header: "", render: row => <button className="icon-button" title={`Details ${row.supplier_code}`} aria-label={`Details ${row.supplier_code}`} onClick={() => inspect(row)}><Search size={16} /></button> }
  ] as Column<SupplierCatalogProduct>[]).map(column => {
    const key = sortKeys[column.key];
    return key ? { ...column, sortable: true, sortDirection: sortBy === key ? sortDirection : null,
      onSort: () => { setSortBy(key); setSortDirection(sortBy === key && sortDirection === "asc" ? "desc" : "asc"); setOffset(0); } } : column;
  });
  const periodColumns: Column<SupplierCatalogPeriod["rows"][number]>[] = [
    {key: "supplier", header: "Supplier", render: row => <div className="supplier-catalog-stack">{row.supplier}<small>{row.vat_number || "-"}</small></div>},
    {key: "invoices", header: "Invoices / credits", align: "right", render: row => `${row.invoices} / ${row.credit_notes}`},
    {key: "purchases", header: "AADE purchases (net)", align: "right", render: row => <span title="Full AADE purchase invoices, including invoice freight and other charges. Cancelled and duplicate records excluded.">{money(row.purchases_net)}</span>},
    {key: "credits", header: "Credits (net)", align: "right", render: row => money(row.credits_net)},
    {key: "net", header: "Net purchases", align: "right", render: row => money(row.net_purchases)},
    {key: "costed", header: "Costed products (net)", align: "right", render: row => money(row.costed_products_net)},
    {key: "units", header: "Units with margin / costed", align: "right", render: row => `${percent.format(Number(row.priced_units))} / ${percent.format(Number(row.costed_units))}`},
    {key: "profit", header: "Avg gross profit / unit (net)", align: "right", render: row => <span title="Current net INDE prices minus invoice product costs, weighted by purchased quantities. Not realized sales profit; excludes freight, ads and other expenses.">{money(row.average_profit_per_unit)}</span>},
    {key: "margin", header: "Weighted gross margin %", align: "right", render: row => <span title="Total potential gross profit / total net catalog selling value of priced purchased units.">{row.average_margin_percent == null ? "-" : `${percent.format(Number(row.average_margin_percent))}%`}</span>},
  ];
  const description = details?.details.description ? new DOMParser().parseFromString(details.details.description, "text/html").body.textContent : "";

  return <div className="page-stack">
    <header className="page-header"><div><h1>Supplier catalog</h1></div>
      <div className="supplier-catalog-actions"><label>From<input aria-label="Period from" type="date" value={costStart} onChange={event=>setCostStart(event.target.value)}/></label>
        <label>To<input aria-label="Period to" type="date" value={costEnd} onChange={event=>setCostEnd(event.target.value)}/></label>
        <button className="secondary-action compact" disabled={loading || periodLoading} onClick={()=>{load();loadPeriod();}}><RefreshCw size={16} />Refresh</button>
        <button className="primary-action compact" disabled={openingCosts} onClick={openCosts}><Download size={16}/>AADE costs</button>
        <button className="primary-action compact" disabled={!selected || queuing || ["queued", "running"].includes(selected.status)} onClick={sync}><RefreshCw size={16} />Sync XML</button></div>
    </header>
    {error && <div className="notice" role="alert">{error}</div>}
    {selected?.error && <div className="notice">{selected.error}</div>}
    <section className="supplier-catalog-period" aria-label="Supplier purchases and margins">
      <h2>Supplier purchases & margins</h2>
      {periodError && <div className="notice" role="alert">{periodError}</div>}
      {periodLoading ? <div role="status">Loading supplier purchases...</div> : <DataTable rows={period?.rows ?? []} columns={periodColumns} rowKey={row=>row.feed_id} empty="No supplier purchases found."/>}
      {period?.rows.some(row=>row.excluded_conflicts > 0) && <div className="notice" role="status">Conflicting AADE invoice totals require review and are excluded.</div>}
    </section>
    <div className="supplier-catalog-filters">
      <label><span>Supplier</span><select aria-label="Supplier" value={feedId} onChange={event => { setFeedId(event.target.value); setCategory(""); setOffset(0); }}>
        <option value="">All suppliers</option>{feeds.map(feed => <option key={feed.id} value={feed.id}>{feed.name}</option>)}
      </select></label>
      <label><span>Search</span><input type="search" value={query} maxLength={200} onChange={event => setQuery(event.target.value)} /></label>
      <label><span>INDE catalog</span><select aria-label="INDE catalog" value={match} onChange={event => { setMatch(event.target.value); setOffset(0); }}>
        <option value="all">All products</option><option value="matched">Matched</option><option value="unmatched">Not matched</option>
      </select></label>
      <label><span>Supplier stock</span><select aria-label="Supplier stock" value={availability} onChange={event => { setAvailability(event.target.value); setOffset(0); }}>
        <option value="all">All stock</option><option value="in_stock">In stock</option><option value="out_of_stock">Out of stock</option>
      </select></label>
      <label><span>Category</span><select aria-label="Category" value={category} onChange={event => { setCategory(event.target.value); setOffset(0); }}>
        <option value="">All categories</option>{result?.categories.map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label className="supplier-margin-filter"><input type="checkbox" checked={hasMargin} onChange={event=>{setHasMargin(event.target.checked);setOffset(0);}}/><span>Only with gross margin</span></label>
    </div>
    <div className="supplier-catalog-summary" aria-live="polite">
      <span>Products <strong>{result?.summary.products ?? 0}</strong></span><span>Matched <strong>{result?.summary.matched ?? 0}</strong></span>
      <span>Not matched <strong>{result?.summary.unmatched ?? 0}</strong></span>
      {selected && <span>{selected.status} · {timestamp(selected.last_synced_at)}</span>}
    </div>
    <div className="supplier-catalog-table" aria-busy={loading}><DataTable rows={loading ? [] : result?.rows ?? []} columns={columns} rowKey={row=>row.id} empty={loading ? "Loading supplier products..." : "No supplier products found."} /></div>
    <div className="supplier-catalog-pagination">
      <button className="icon-button" title="Previous page" aria-label="Previous page" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}><ChevronLeft size={17} /></button>
      <span>{result?.total ? `${offset + 1}-${Math.min(offset + 50, result.total)} / ${result.total}` : "0"}</span>
      <button className="icon-button" title="Next page" aria-label="Next page" disabled={loading || !result || offset + 50 >= result.total} onClick={() => setOffset(offset + 50)}><ChevronRight size={17} /></button>
    </div>
    {showCosts && <div className="modal-backdrop" onClick={()=>setShowCosts(false)}>
      <section className="supplier-catalog-dialog supplier-cost-dialog" role="dialog" aria-modal="true" aria-label="Import AADE purchase costs" onClick={event=>event.stopPropagation()}>
        <div className="panel-title"><h2>AADE purchase costs</h2><button className="icon-button" autoFocus title="Close cost import" aria-label="Close cost import" onClick={()=>setShowCosts(false)}><X size={18}/></button></div>
        <div className="supplier-catalog-actions"><label>From<input aria-label="Cost invoices from" type="date" value={costStart} onChange={event=>setCostStart(event.target.value)}/></label>
          <label>To<input aria-label="Cost invoices to" type="date" value={costEnd} onChange={event=>setCostEnd(event.target.value)}/></label></div>
        <SupplierAADEPanel start={costStart} end={costEnd} initialSupplier={costSupplier} onImported={()=>{load();loadPeriod();}} onSettings={()=>{setShowCosts(false);window.location.hash="settings";}}/>
      </section>
    </div>}
    {details && <div className="modal-backdrop" onClick={() => { detailId.current++; setDetails(null); }}>
      <section className="supplier-catalog-dialog" role="dialog" aria-modal="true" aria-label={details.name} onClick={event => event.stopPropagation()}>
        <div className="panel-title"><h2>{details.name}</h2><button className="icon-button" autoFocus title="Close product" aria-label="Close product" onClick={() => { detailId.current++; setDetails(null); }}><X size={18} /></button></div>
        <p>{details.details.availability || "-"}</p>
        <div className="supplier-package-table"><table className="data-table">
          <thead><tr><th>Package</th><th>Width (cm)</th><th>Length (cm)</th><th>Height (cm)</th><th>Volume (m³)</th><th>Volumetric (kg) / {details.volumetric_divisor}</th></tr></thead>
          <tbody>{(details.packages ?? []).map(row => <tr key={row.label}><td>{row.label}</td><td>{row.width_cm ?? "-"}</td><td>{row.length_cm ?? "-"}</td><td>{row.height_cm ?? "-"}</td><td>{row.volume_m3 == null ? "-" : Number(row.volume_m3).toLocaleString("el-GR", {maximumFractionDigits: 6})}</td><td>{row.volumetric_kg == null ? "-" : Number(row.volumetric_kg).toLocaleString("el-GR", {maximumFractionDigits: 2})}</td></tr>)}{!details.packages?.length && <tr><td colSpan={6}>No package dimensions in supplier XML.</td></tr>}</tbody>
          {details.volume_total_m3 != null && <tfoot><tr><th>Total</th><td colSpan={3}/><td>{Number(details.volume_total_m3).toLocaleString("el-GR", {maximumFractionDigits: 6})}</td><td>{Number(details.volumetric_total_kg).toLocaleString("el-GR", {maximumFractionDigits: 2})}</td></tr></tfoot>}
        </table></div>
        <dl className="supplier-catalog-detail-grid">
          <div><dt>Supplier volume (raw)</dt><dd>{details.details.volume_item ?? details.details.volume ?? "-"}</dd></div>
          <div><dt>Supplier weight (raw)</dt><dd>{details.details.weight_item ?? details.details.weight ?? "-"}</dd></div>
          <div><dt>Packages / item</dt><dd>{details.details.packages_per_item ?? "-"}</dd></div>
          <div><dt>Supplier combined dimensions (cm)</dt><dd>{[details.details.comb_width_cm, details.details.comb_length_cm, details.details.comb_height_cm].every(value => value && Number(value) > 0) ? `${details.details.comb_width_cm} × ${details.details.comb_length_cm} × ${details.details.comb_height_cm}` : "-"}</dd></div>
          {details.details.filters.map((filter, index) => <div key={index}><dt>{filter.group}</dt><dd>{filter.value}</dd></div>)}
          {details.details.net_price != null && <div><dt>XML net_price (tax basis unconfirmed)</dt><dd>{money(Number(details.details.net_price))}</dd></div>}
          {details.details.stock_price != null && <div><dt>XML stock_price (tax basis unconfirmed)</dt><dd>{money(Number(details.details.stock_price))}</dd></div>}
          {details.details.sell_step != null && <div><dt>Supplier sell step</dt><dd>{details.details.sell_step}</dd></div>}
          {details.details.date_expected && <div><dt>Expected availability</dt><dd>{details.details.date_expected}</dd></div>}
          {details.details.attributes?.map((attribute, index) => <div key={`attribute-${index}`}><dt>Supplier attribute {attribute.id}</dt><dd>{attribute.value}</dd></div>)}
        </dl>
        <p className="supplier-catalog-description">{description}</p>
      </section>
    </div>}
  </div>;
}
