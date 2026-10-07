import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, RefreshCw, Settings, X } from "lucide-react";
import { api, type SupplierIdentity, type SupplierAADEInvoice, type SupplierAADEPreview } from "../api/client";
import { DataTable } from "./DataTable";

const eur = new Intl.NumberFormat("el-GR", {style:"currency", currency:"EUR"});
const money = (value: number | null) => value === null ? "-" : eur.format(value);
type InvoiceReview = { preview: SupplierAADEPreview | null; confirmed: boolean; loading: boolean; accepting: boolean; error: string; notice: string };

export function SupplierAADEPanel({start, end, onImported, onSettings, initialSupplier = ""}: {start:string; end:string; onImported:()=>void; onSettings:()=>void; initialSupplier?:string}) {
  const [suppliers, setSuppliers] = useState<SupplierIdentity[]>([]);
  const [supplier, setSupplier] = useState(initialSupplier);
  const [rows, setRows] = useState<SupplierAADEInvoice[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [reviews, setReviews] = useState<Record<string, InvoiceReview>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const reviewRequests = useRef(new Map<string, object>());
  function clearReviews() { reviewRequests.current.clear(); setReviews({}); }
  function closeReview(id: string) {
    reviewRequests.current.delete(id);
    setReviews(current => { const next = {...current}; delete next[id]; return next; });
  }
  function updateReview(id: string, patch: Partial<InvoiceReview>) {
    setReviews(current => current[id] ? {...current, [id]: {...current[id], ...patch}} : current);
  }
  useEffect(() => { api.supplierIdentities().then(result => setSuppliers(result.data.rows)).catch(err => setError(err.message)); }, []);
  useEffect(() => {
    sequence.current++; setRows([]); setTotal(0); setOffset(0); clearReviews(); setBusy(false); setError("");
    return () => { sequence.current++; reviewRequests.current.clear(); };
  }, [supplier, start, end]);
  async function load(page = 0) {
    const seq = ++sequence.current; setBusy(true); setError(""); clearReviews();
    try {
      const result = await api.supplierAADEInvoices(supplier, start, end, page);
      if (seq !== sequence.current) return;
      setRows(result.data.rows); setTotal(result.data.total); setOffset(page);
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Invoice list failed."); }
    finally { if (seq === sequence.current) setBusy(false); }
  }
  useEffect(() => { if (initialSupplier) load(); }, [initialSupplier]);
  async function inspect(row: SupplierAADEInvoice) {
    const request = {}; reviewRequests.current.set(row.id, request);
    setReviews(current => ({...current, [row.id]: {preview:null, confirmed:false, loading:true, accepting:false, error:"", notice:""}}));
    // Closing or changing the invoice list invalidates only the relevant responses.
    const active = () => reviewRequests.current.get(row.id) === request;
    try { const result = await api.supplierAADEPreview(row.id, supplier); if (active()) updateReview(row.id, {preview:result.data}); }
    catch (err) { if (active()) updateReview(row.id, {error:err instanceof Error ? err.message : "Invoice preview failed."}); }
    finally { if (active()) updateReview(row.id, {loading:false}); }
  }
  async function accept(id: string) {
    const review = reviews[id];
    if (!review?.preview || !review.confirmed || review.accepting || review.loading) return;
    const preview = review.preview;
    const request = reviewRequests.current.get(id);
    const active = () => request !== undefined && reviewRequests.current.get(id) === request;
    updateReview(id, {accepting:true, error:"", notice:""});
    try {
      const result = await api.acceptSupplierAADEInvoice(preview);
      onImported();
      if (!active()) return;
      updateReview(id, {confirmed:false, preview:{...preview, can_import:false, imported:true}, notice:result.data.duplicate ? "Invoice already imported." : `${result.data.costs_created} AADE product costs saved.`});
      const next = await api.supplierAADEPreview(preview.id, supplier);
      if (active()) updateReview(id, {preview:next.data});
    } catch (err) { if (active()) updateReview(id, {error:err instanceof Error ? err.message : "Invoice was not imported."}); }
    finally { if (active()) updateReview(id, {accepting:false}); }
  }
  function expandedReview(row: SupplierAADEInvoice) {
    const review = reviews[row.id];
    if (!review) return null;
    const preview = review.preview;
    return <section id={`aade-review-${row.id}`} className="supplier-aade-review" aria-label={`Invoice details ${row.number}`} aria-busy={review.loading || review.accepting}>
      <div className="panel-title"><h2>{preview ? `${preview.supplier} / ${preview.number}` : row.number}</h2><button className="icon-button" aria-label={`Close invoice preview ${row.number}`} title="Close invoice preview" onClick={()=>closeReview(row.id)}><X size={17}/></button></div>
      {review.loading && <p role="status">Loading invoice...</p>}
      {review.error && <div className="notice error" role="alert">{review.error}</div>}
      {review.notice && <div className="notice success" role="status">{review.notice}</div>}
      {!preview && !review.loading && <button className="icon-button" aria-label={`Retry invoice ${row.number}`} title="Retry invoice" onClick={()=>inspect(row)}><RefreshCw size={17}/></button>}
      {preview && <>
        <p>{preview.date} · AFM {preview.issuer_vat} · MARK {preview.mark} · Net {money(preview.net_value)} · VAT {money(preview.vat_amount)} · Total {money(preview.gross_value)}</p>
        {preview.reasons.map(reason=><div className="notice" key={reason}>{reason}</div>)}
        <DataTable rows={preview.lines} empty="No invoice lines." columns={[
          {key:"line", header:"Line", render:line=>line.line_number}, {key:"code", header:"Invoice code", render:line=>line.item_code || "-"},
          {key:"name", header:"Description", render:line=>line.description}, {key:"sku", header:"INDE SKU", render:line=>line.inde_sku || "-"},
          {key:"type", header:"Type", render:line=>line.line_type}, {key:"qty", header:"Qty", align:"right", render:line=>line.quantity ?? "-"},
          {key:"unit", header:"Unit", render:line=>line.unit || "-"}, {key:"cost", header:"Net cost / piece", align:"right", render:line=>money(line.unit_cost_net)},
          {key:"net", header:"Net", align:"right", render:line=>money(line.net_value)}, {key:"vat", header:"VAT", align:"right", render:line=>money(line.vat_amount)},
          {key:"review", header:"Review", render:line=>line.reasons.join(" ") || (line.line_type==="shipping" ? "Excluded from product cost" : "Exact XML identifiers")}
        ]}/>
        {preview.can_import && <><label className="supplier-feed-toggle"><input type="checkbox" checked={review.confirmed} disabled={review.accepting} onChange={event=>updateReview(row.id, {confirmed:event.target.checked})}/>Verified products; one purchase piece equals one INDE sales unit</label>
          <button className="primary-action compact" disabled={review.accepting || !review.confirmed} onClick={()=>accept(row.id)}><Check size={16}/>Accept AADE costs</button></>}
      </>}
    </section>;
  }
  return <section className="panel supplier-aade-panel" aria-label="AADE purchase costs">
    <div className="panel-title"><h2>AADE purchase costs</h2><button className="icon-button" onClick={onSettings} title="Supplier AFM settings" aria-label="Supplier AFM settings"><Settings size={18}/></button></div>
    <div className="supplier-catalog-actions">
      <label><span>Supplier</span><select aria-label="AADE supplier" value={supplier} disabled={busy} onChange={event => setSupplier(event.target.value)}>
        <option value="">Select supplier</option>{suppliers.filter(row => row.id && row.vat_number).map(row => <option key={row.id} value={row.id!}>{row.name} · {row.vat_number}</option>)}
      </select></label>
      <button className="primary-action compact" onClick={() => load()} disabled={busy || !supplier}><RefreshCw size={16}/>Load invoices</button>
      <span>{start} / {end}</span>
    </div>
    {error && <div className="notice error" role="alert">{error}</div>}
    <DataTable rows={rows} rowKey={row=>row.id} renderExpandedRow={expandedReview} empty={busy ? "Loading invoices..." : "No invoices loaded."} columns={[
      {key:"date", header:"Date", render:row=>row.date}, {key:"number", header:"Invoice", render:row=>row.number},
      {key:"type", header:"Type", render:row=>row.invoice_type}, {key:"record", header:"Record", render:row=>row.record_type},
      {key:"mark", header:"MARK", render:row=>row.mark || "-"}, {key:"net", header:"Net", align:"right", render:row=>money(row.net_value)},
      {key:"gross", header:"Total", align:"right", render:row=>money(row.gross_value)},
      {key:"status", header:"Status", render:row=>row.cancelled ? "Cancelled" : "Active"},
      {key:"view", header:"", render:row=><button className="icon-button" aria-label={`Review invoice ${row.number}`} aria-expanded={!!reviews[row.id]} aria-controls={reviews[row.id] ? `aade-review-${row.id}` : undefined} title={reviews[row.id] ? "Close invoice preview" : "Review invoice"} disabled={busy} onClick={()=>reviews[row.id] ? closeReview(row.id) : inspect(row)}>{reviews[row.id] ? <ChevronUp size={16}/> : <ChevronDown size={16}/>}</button>}
    ]}/>
    <div className="supplier-catalog-actions">
      <button className="icon-button" title="Previous invoices" aria-label="Previous invoices" disabled={busy || offset===0} onClick={()=>load(Math.max(0,offset-50))}><ChevronLeft size={18}/></button>
      <span>{total ? `${offset+1} - ${Math.min(offset+50,total)} / ${total}` : "0"}</span>
      <button className="icon-button" title="Next invoices" aria-label="Next invoices" disabled={busy || offset+50>=total} onClick={()=>load(offset+50)}><ChevronRight size={18}/></button>
    </div>
  </section>;
}
