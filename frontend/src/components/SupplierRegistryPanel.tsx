import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FileSearch, Plus, Settings } from "lucide-react";
import { api, type SupplierRegistryRow } from "../api/client";
import { DataTable } from "./DataTable";

export function SupplierRegistryPanel({start, end, onInvoices, onImported, onSettings}: {
  start:string; end:string; onInvoices:(id:string)=>void; onImported:()=>void; onSettings:()=>void;
}) {
  const [rows, setRows] = useState<SupplierRegistryRow[]>([]);
  const [skipped, setSkipped] = useState(0);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const sequence = useRef(0);
  async function load() {
    const seq = ++sequence.current; setLoading(true); setError("");
    try {
      const result = await api.supplierAADERegistry(start, end);
      if (seq === sequence.current) { setRows(result.data.rows); setSkipped(result.data.skipped_records); setOffset(0); }
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Supplier list failed."); }
    finally { if (seq === sequence.current) setLoading(false); }
  }
  useEffect(() => { setRows([]); setNotice(""); load(); return () => { sequence.current++; }; }, [start, end]);
  async function importAll() {
    setSaving(true); setError(""); setNotice("");
    const seq = sequence.current;
    try {
      const result = (await api.importAADESuppliers()).data;
      onImported();
      if (seq !== sequence.current) return;
      setNotice(`${result.created} suppliers added; ${result.existing} already registered; ${result.names_updated} names updated; ${result.conflicts} conflicts need review.`);
      await load();
    } catch (err) { if (seq === sequence.current) setError(err instanceof Error ? err.message : "Suppliers were not added."); }
    finally { setSaving(false); }
  }
  const filtered = rows.filter(row=>[row.name, row.vat_number, row.code].join(" ").toLowerCase().includes(search.toLowerCase()));
  const count = new Intl.NumberFormat("el-GR");
  return <section className="panel supplier-registry-panel" aria-label="Supplier registry">
    <div className="panel-title"><h2>Suppliers</h2><span>{count.format(rows.filter(row=>row.id).length)} registered / {count.format(rows.length)} total</span></div>
    <div className="supplier-catalog-actions">
      <input className="supplier-filter" aria-label="Search supplier registry" placeholder="Company, AFM or supplier code" value={search} onChange={event=>{setSearch(event.target.value);setOffset(0);}}/>
      <button className="primary-action compact" disabled={loading || saving} onClick={importAll}><Plus size={16}/>Add AADE suppliers</button>
      <button className="icon-button" aria-label="Supplier AFM settings" title="Supplier AFM settings" onClick={onSettings}><Settings size={18}/></button>
    </div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {notice && <div className="notice success" role="status">{notice}</div>}
    {!!skipped && <div className="notice">{count.format(skipped)} AADE records excluded: missing/invalid supplier AFM, other recipient or non-supplier records.</div>}
    <DataTable rows={filtered.slice(offset, offset+50)} rowKey={row=>row.vat_number} empty={loading ? "Loading suppliers..." : "No suppliers found."} columns={[
      {key:"name",header:"Company",render:row=><div className="stacked-cell"><span>{row.name}</span>{row.name_pending && <small>Company name pending</small>}</div>},
      {key:"vat",header:"AFM / VAT",render:row=>row.vat_number},
      {key:"code",header:"Supplier code",render:row=>row.code || "-"},
      {key:"source",header:"Source",render:row=>row.source},
      {key:"period",header:"Documents in period",align:"right",render:row=>count.format(row.period_documents)},
      {key:"all",header:"All documents",align:"right",render:row=>count.format(row.documents)},
      {key:"last",header:"Last document",render:row=>row.last_document_date || "-"},
      {key:"status",header:"Status",render:row=>row.identity_conflict ? "AFM conflict" : row.id ? "Registered" : "Not registered"},
      {key:"invoices",header:"",render:row=><button className="icon-button" title="View invoices" aria-label={`View invoices ${row.vat_number}`} disabled={!row.id || saving || loading} onClick={()=>onInvoices(row.id!)}><FileSearch size={17}/></button>}
    ]}/>
    <div className="supplier-catalog-actions">
      <button className="icon-button" title="Previous suppliers" aria-label="Previous suppliers" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-50))}><ChevronLeft size={18}/></button>
      <span>{filtered.length ? `${offset+1} - ${Math.min(offset+50,filtered.length)} / ${filtered.length}` : "0"}</span>
      <button className="icon-button" title="Next suppliers" aria-label="Next suppliers" disabled={offset+50>=filtered.length} onClick={()=>setOffset(offset+50)}><ChevronRight size={18}/></button>
    </div>
  </section>;
}
