import { useEffect, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Mail, RefreshCw, Search, X } from "lucide-react";
import { api, type SupplierGmailSource, type SupplierGmailJob } from "../api/client";
import { DataTable, type Column } from "./DataTable";

const euros = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const amount = (value: string) => euros.format(Number(value));
const day = (offset: number) => { const date = new Date(); date.setDate(date.getDate() + offset); return date.toISOString().slice(0, 10); };

export function SupplierGmailPanel({ onImported }: { onImported: () => Promise<void> }) {
  const [rows, setRows] = useState<SupplierGmailSource[]>([]);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [automatic, setAutomatic] = useState(false);
  const [interval, setIntervalMinutes] = useState(15);
  const [job, setJob] = useState<SupplierGmailJob | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [from, setFrom] = useState(day(-7));
  const [to, setTo] = useState(day(0));
  const [selected, setSelected] = useState<SupplierGmailSource | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [freeShipping, setFreeShipping] = useState(false);
  const [net, setNet] = useState("");
  const [vat, setVat] = useState("");
  function receive(result: Awaited<ReturnType<typeof api.supplierGmailSources>>) {
    setRows(result.data.rows); setConfigured(result.data.configured); setAutomatic(result.data.automatic);
    setIntervalMinutes(result.data.interval_minutes); setJob(result.data.job); setError("");
  }
  async function load(nextOffset = offset) {
    setLoading(true);
    try { receive(await api.supplierGmailSources(nextOffset)); }
    catch (err) { setConfigured(null); setError(err instanceof Error ? err.message : "Unable to load Gmail documents."); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    let active = true, polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      try { const result = await api.supplierGmailSources(offset); if (active) receive(result); }
      catch (err) { if (active) { setConfigured(null); setError(err instanceof Error ? err.message : "Unable to load Gmail documents."); } }
      finally { polling = false; if (active) setLoading(false); }
    }
    setLoading(true); void poll();
    const timer = window.setInterval(poll, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [offset]);
  async function sync() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.syncSupplierGmail(from, to);
      setJob(result.data.job); setNotice("Gmail read queued.");
      setOffset(0); await load(0);
    } catch (err) { setError(err instanceof Error ? err.message : "Gmail read failed."); }
    finally { setBusy(false); }
  }
  function open(row: SupplierGmailSource) { setSelected(row); setNet(""); setVat(""); setConfirmed(false); setFreeShipping(false); setError(""); }
  async function review(action: "approve" | "reject") {
    if (!selected) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api.reviewSupplierGmail(selected.id, { action, ...(action === "approve" ? {
        confirm_supplier_order: confirmed, shipping_waived: freeShipping,
        shipping_net: freeShipping ? "0" : net, shipping_vat: freeShipping ? "0" : vat
      } : {}) });
      setSelected(null); setNotice(action === "approve" ? "Cost evidence accepted." : "Document rejected.");
      await load(); await onImported();
    } catch (err) { setError(err instanceof Error ? err.message : "Document review failed."); }
    finally { setBusy(false); }
  }
  const columns: Column<SupplierGmailSource>[] = [
    { key: "supplier", header: "Supplier", render: () => "MEGAPAP" },
    { key: "document", header: "Document", render: row => <div className="stacked-cell"><strong>{row.payload.documents?.[0]?.document_number || "-"}</strong><span>{row.filename || "Email body"}</span></div> },
    { key: "date", header: "Document date", render: row => row.payload.documents?.[0]?.document_date || "-" },
    { key: "status", header: "Status", render: row => row.status },
    { key: "reason", header: "Reason", render: row => row.reason || "-" },
    { key: "review", header: "", render: row => <button className="icon-button" title="Review document" aria-label={`Review document ${row.payload.documents?.[0]?.document_number || row.filename || row.id}`} disabled={busy} onClick={() => open(row)}><Search size={16} /></button> }
  ];
  const document = selected?.payload.documents?.[0];
  const pending = selected && ["pending", "review"].includes(selected.status);
  const products = document?.lines.filter(line => line.line_type === "product") || [];
  const productColumns: Column<(typeof products)[number]>[] = [
    { key: "sku", header: "Supplier SKU", render: row => row.supplier_sku || "-" },
    { key: "code", header: "Supplier code", render: row => row.supplier_code || "-" },
    { key: "description", header: "Description", render: row => row.description },
    { key: "qty", header: "Quantity", align: "right", render: row => row.quantity },
    { key: "cost", header: "Unit cost net", align: "right", render: row => amount(row.unit_price_before_discount) },
    { key: "total", header: "Line net", align: "right", render: row => amount(row.net_line_total) }
  ];
  return <section className="panel supplier-gmail">
    <div className="panel-title"><h2><Mail size={18} /> MEGAPAP documents</h2><span>info@inde.gr | {configured === null ? "Connection status unavailable" : configured ? "Configured" : "Not configured"}{configured && automatic ? ` | Auto: ${interval} min` : ""}</span></div>
    <div className="supplier-gmail-controls">
      <label>Received from<input type="date" value={from} max={to} onChange={event => setFrom(event.target.value)} /></label>
      <label>Received to<input type="date" value={to} min={from} onChange={event => setTo(event.target.value)} /></label>
      <button className="primary-action" disabled={!configured || busy || !from || !to || from > to || job?.status === "queued" || job?.status === "running"} onClick={() => sync()}><RefreshCw size={16} /> Read Gmail</button>
      <button className="icon-button" title="Refresh Gmail documents" aria-label="Refresh Gmail documents" disabled={busy || loading} onClick={() => load()}><RefreshCw size={16} /></button>
    </div>
    {job && <p role="status">{job.mode} | {job.status} | {job.date_from} - {job.date_to} | Pages: {job.pages} | Messages: {job.counts.messages || 0} | Pending: {job.counts.pending || 0} | Review: {job.counts.review || 0} | Duplicates: {job.counts.duplicate || 0} | Previously received: {job.counts.existing || 0} | Skipped: {job.counts.skipped || 0}</p>}
    {job?.error && <p className="error-message" role="alert">{job.error}</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {loading ? <p role="status">Loading documents...</p> : <DataTable rows={rows} columns={columns} empty="No Gmail documents received." />}
    <div className="supplier-gmail-pagination"><button className="icon-button" title="Previous documents" aria-label="Previous documents" disabled={offset === 0 || busy || loading} onClick={() => { setSelected(null); setOffset(offset - 100); }}><ChevronLeft size={16} /></button><span>{rows.length ? `${offset + 1} - ${offset + rows.length}` : "0"}</span><button className="icon-button" title="Next documents" aria-label="Next documents" disabled={rows.length < 100 || busy || loading} onClick={() => { setSelected(null); setOffset(offset + 100); }}><ChevronRight size={16} /></button></div>
    {selected && <div className="supplier-gmail-review">
      <div className="panel-title"><h2>MEGAPAP / {document?.document_number || selected.filename || "Document review"}</h2><button className="icon-button" title="Close review" aria-label="Close review" disabled={busy} onClick={() => setSelected(null)}><X size={16} /></button></div>
      <p>{document?.document_type || selected.status} | {document?.document_date || "-"} | {selected.reason || "Accepted"}</p>
      {document && <><div className="supplier-gmail-totals"><span>Products net: <strong>{amount(document.net_products_total)}</strong></span><span>Displayed freight: <strong>{amount(document.net_shipping_total)}</strong></span><span>Product VAT: <strong>{amount(document.vat_total)}</strong></span><span>Original order total: <strong>{amount(document.gross_total)}</strong></span>{pending && freeShipping && <><span>Freight cost: <strong>{amount("0")}</strong></span><span>Cost total: <strong>{euros.format(Number(document.gross_total) - Number(document.net_shipping_total))}</strong></span></>}</div><DataTable rows={products} columns={productColumns} empty="No product lines." /></>}
      {pending && <form onSubmit={event => { event.preventDefault(); review("approve"); }}>
        {document && <><label className="supplier-gmail-confirm"><input type="checkbox" checked={freeShipping} onChange={event => setFreeShipping(event.target.checked)} />Free shipping - supplier removes freight at invoicing</label>{!freeShipping && <div className="supplier-gmail-controls"><label>Confirmed freight net<input type="number" min="0" step="0.01" required value={net} onChange={event => setNet(event.target.value)} /></label><label>Confirmed freight VAT<input type="number" min="0" step="0.01" required value={vat} onChange={event => setVat(event.target.value)} /></label></div>}<label className="supplier-gmail-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />Supplier order cost evidence, not a fiscal invoice</label></>}
        <div className="supplier-gmail-controls">{document && <button className="primary-action" disabled={busy || !confirmed || (!freeShipping && (net === "" || vat === ""))} type="submit"><Check size={16} /> Accept cost evidence</button>}<button className="secondary-action" disabled={busy} type="button" onClick={() => review("reject")}><X size={16} /> Reject document</button></div>
      </form>}
    </div>}
  </section>;
}
