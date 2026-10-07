import { useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Search, RefreshCw, Settings, X } from "lucide-react";
import { api, type SupplierIdentity, type SupplierAADEInvoice, type SupplierAADEPreview } from "../api/client";
import { DataTable } from "./DataTable";

const eur = new Intl.NumberFormat("el-GR", {style:"currency", currency:"EUR"});
const money = (value: number | null) => value === null ? "-" : eur.format(value);

export function SupplierAADEPanel({start, end, onImported, onSettings}: {start:string; end:string; onImported:()=>void; onSettings:()=>void}) {
  const [suppliers, setSuppliers] = useState<SupplierIdentity[]>([]);
  const [supplier, setSupplier] = useState("");
  const [rows, setRows] = useState<SupplierAADEInvoice[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<SupplierAADEPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const sequence = useRef(0);
  useEffect(() => { api.supplierIdentities().then(result => setSuppliers(result.data.rows)).catch(err => setError(err.message)); }, []);
  useEffect(() => { sequence.current++; setRows([]); setTotal(0); setOffset(0); setPreview(null); setConfirmed(false); setBusy(false); }, [supplier, start, end]);
  async function load(page = 0) {
    const seq = ++sequence.current; setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try {
      const result = await api.supplierAADEInvoices(supplier, start, end, page);
      if (seq !== sequence.current) return;
      setRows(result.data.rows); setTotal(result.data.total); setOffset(page);
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Invoice list failed."); }
    finally { if (seq === sequence.current) setBusy(false); }
  }
  async function inspect(row: SupplierAADEInvoice) {
    const seq = ++sequence.current; setBusy(true); setError(""); setPreview(null); setConfirmed(false); setNotice("");
    try { const result = await api.supplierAADEPreview(row.id, supplier); if (seq === sequence.current) setPreview(result.data); }
    catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Invoice preview failed."); }
    finally { if (seq === sequence.current) setBusy(false); }
  }
  async function accept() {
    if (!preview || !confirmed) return;
    const seq = ++sequence.current;
    setBusy(true); setError("");
    try {
      const result = await api.acceptSupplierAADEInvoice(preview);
      onImported();
      if (seq !== sequence.current) return;
      setNotice(result.data.duplicate ? "Invoice already imported." : `${result.data.costs_created} AADE product costs saved.`);
      const next = await api.supplierAADEPreview(preview.id, supplier);
      if (seq === sequence.current) { setPreview(next.data); setConfirmed(false); }
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Invoice was not imported."); }
    finally { if (seq === sequence.current) setBusy(false); }
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
    {notice && <div className="notice success" role="status">{notice}</div>}
    <DataTable rows={rows} empty={busy ? "Loading invoices..." : "No invoices loaded."} columns={[
      {key:"date", header:"Date", render:row=>row.date}, {key:"number", header:"Invoice", render:row=>row.number},
      {key:"type", header:"Type", render:row=>row.invoice_type}, {key:"record", header:"Record", render:row=>row.record_type},
      {key:"mark", header:"MARK", render:row=>row.mark || "-"}, {key:"net", header:"Net", align:"right", render:row=>money(row.net_value)},
      {key:"gross", header:"Total", align:"right", render:row=>money(row.gross_value)},
      {key:"status", header:"Status", render:row=>row.cancelled ? "Cancelled" : "Active"},
      {key:"view", header:"", render:row=><button className="icon-button" aria-label={`Review invoice ${row.number}`} title="Review invoice" disabled={busy} onClick={()=>inspect(row)}><Search size={16}/></button>}
    ]}/>
    <div className="supplier-catalog-actions">
      <button className="icon-button" title="Previous invoices" aria-label="Previous invoices" disabled={busy || offset===0} onClick={()=>load(Math.max(0,offset-50))}><ChevronLeft size={18}/></button>
      <span>{total ? `${offset+1} - ${Math.min(offset+50,total)} / ${total}` : "0"}</span>
      <button className="icon-button" title="Next invoices" aria-label="Next invoices" disabled={busy || offset+50>=total} onClick={()=>load(offset+50)}><ChevronRight size={18}/></button>
    </div>
    {preview && <div className="supplier-aade-review">
      <div className="panel-title"><h2>{preview.supplier} / {preview.number}</h2><button className="icon-button" aria-label="Close invoice preview" title="Close invoice preview" disabled={busy} onClick={()=>setPreview(null)}><X size={17}/></button></div>
      <p>{preview.date} · AFM {preview.issuer_vat} · MARK {preview.mark} · Net {money(preview.net_value)} · VAT {money(preview.vat_amount)} · Total {money(preview.gross_value)}</p>
      {preview.reasons.map(reason=><div className="notice" key={reason}>{reason}</div>)}
      <DataTable rows={preview.lines} empty="No invoice lines." columns={[
        {key:"line", header:"Line", render:row=>row.line_number}, {key:"code", header:"Invoice code", render:row=>row.item_code || "-"},
        {key:"name", header:"Description", render:row=>row.description}, {key:"sku", header:"INDE SKU", render:row=>row.inde_sku || "-"},
        {key:"type", header:"Type", render:row=>row.line_type}, {key:"qty", header:"Qty", align:"right", render:row=>row.quantity ?? "-"},
        {key:"unit", header:"Unit", render:row=>row.unit || "-"}, {key:"cost", header:"Net cost / piece", align:"right", render:row=>money(row.unit_cost_net)},
        {key:"net", header:"Net", align:"right", render:row=>money(row.net_value)}, {key:"vat", header:"VAT", align:"right", render:row=>money(row.vat_amount)},
        {key:"review", header:"Review", render:row=>row.reasons.join(" ") || (row.line_type==="shipping" ? "Excluded from product cost" : "Exact XML identifiers")}
      ]}/>
      {preview.can_import && <><label className="supplier-feed-toggle"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event=>setConfirmed(event.target.checked)}/>Verified products; one purchase piece equals one INDE sales unit</label>
        <button className="primary-action compact" disabled={busy || !confirmed} onClick={accept}><Check size={16}/>Accept AADE costs</button></>}
    </div>}
  </section>;
}
