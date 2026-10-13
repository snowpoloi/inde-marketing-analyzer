import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, ExternalLink, RefreshCw, Search } from "lucide-react";
import { api } from "../api/client";
import type { PendingCostInvoice, PendingCostLine, PendingCostResult, SupplierIdentity, SupplierMatchCandidate } from "../api/client";
import { DataTable } from "./DataTable";
import type { Column } from "./DataTable";
import { invoiceLink } from "../utils/recordLinks";

const euros = new Intl.NumberFormat("el-GR", {style:"currency", currency:"EUR"});
const money = (value: number | null) => value == null ? "-" : euros.format(Number(value));
const reasonLabels: Record<string, string> = {
  "Ambiguous supplier XML code.": "Ο κωδικός αντιστοιχεί σε περισσότερα προϊόντα XML.",
  "XML product is not linked to an INDE product.": "Το προϊόν XML δεν έχει αντιστοιχιστεί σε προϊόν INDE.",
  "No unique INDE product through this supplier XML.": "Δεν βρέθηκε μοναδική αντιστοίχιση στο XML του προμηθευτή.",
  "No INDE product with the exact Pakketo invoice SKU.": "Δεν βρέθηκε προϊόν INDE με ακριβώς τον κωδικό του τιμολογίου Pakketo.",
  "Reviewed mapping conflicts with the exact Pakketo invoice SKU; reconciliation required.": "Η επιβεβαιωμένη αντιστοίχιση διαφέρει από το ίδιο SKU της INDE. Χρειάζεται έλεγχος.",
  "Existing mapping / pack conversion conflicts with the exact Pakketo invoice SKU.": "Η προηγούμενη αντιστοίχιση ή μονάδα αγοράς διαφέρει από το ίδιο SKU της INDE. Χρειάζεται έλεγχος.",
  "Missing item code; description alone is not an automatic match.": "Λείπει κωδικός είδους στο τιμολόγιο.",
  "Purchase unit is not explicitly pieces; pack conversion requires review.": "Η μονάδα αγοράς δεν έχει επιβεβαιωθεί ως τεμάχιο.",
  "Missing or invalid product quantity.": "Λείπει έγκυρη ποσότητα στο τιμολόγιο.",
  "Invoice totals do not reconcile to the stored lines; fees / discounts require review.": "Οι γραμμές δεν συμφωνούν με τα σύνολα του τιμολογίου.",
  "Book / VAT summaries are not product invoices.": "Υπάρχει μόνο λογιστική σύνοψη, χωρίς αναλυτικό τιμολόγιο.",
  "Invoice is cancelled.": "Το τιμολόγιο έχει ακυρωθεί.",
  "Special fiscal line (fee / tax / adjustment) requires separate review.": "Χρέωση ή φορολογική προσαρμογή, όχι επιβεβαιώσιμο κόστος προϊόντος.",
  "Reviewed product identifiers changed; confirm the mapping again.": "Άλλαξαν οι κωδικοί του επιβεβαιωμένου προϊόντος. Χρειάζεται νέα επιβεβαίωση.",
};
const reason = (value: string) => reasonLabels[value] || value;
type Row = {key: string; invoice: PendingCostInvoice; line: PendingCostLine | null};

function LineReview({invoice, line, onSaved}: {invoice: PendingCostInvoice; line: PendingCostLine; onSaved: () => void}) {
  const [query, setQuery] = useState(line.item_code || "");
  const [candidates, setCandidates] = useState<SupplierMatchCandidate[]>([]);
  const [chosen, setChosen] = useState(line.product_catalog_id || "");
  const [searching, setSearching] = useState(false);
  const [units, setUnits] = useState(Boolean(invoice.confirm_missing_units));
  const [confirmed, setConfirmed] = useState(false);
  const [remember, setRemember] = useState(Boolean(line.item_code));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const searchVersion = useRef(0);
  useEffect(() => {
    const version = ++searchVersion.current;
    if (query.trim().length < 2) {setCandidates([]); setSearching(false); return;}
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const response = await api.supplierCatalogSearch(query.trim());
        if (version === searchVersion.current) {setCandidates(response.data.rows); setError("");}
      } catch (err) {if (version === searchVersion.current) setError(err instanceof Error ? err.message : "Η αναζήτηση απέτυχε.");}
      finally {if (version === searchVersion.current) setSearching(false);}
    }, 300);
    return () => {window.clearTimeout(timer); searchVersion.current++;};
  }, [query]);
  const missingUnit = !line.source_unit && !invoice.confirm_missing_units;
  async function save() {
    if (saving) return;
    setSaving(true); setError("");
    try {
      await api.confirmSupplierCostLine(invoice.id, {
        supplier_id: invoice.supplier_id, line_number: line.line_number, product_catalog_id: chosen,
        fingerprint: invoice.fingerprint, source_digest: invoice.source_digest,
        preview_confirm_missing_units: Boolean(invoice.confirm_missing_units),
        confirm_missing_units: units, confirm_products_and_units: confirmed, remember_match: remember,
      });
      onSaved();
    } catch (err) {setError(err instanceof Error ? err.message : "Η επιβεβαίωση απέτυχε.");}
    finally {setSaving(false);}
  }
  const originalChosen = line.product_catalog_id === chosen && !candidates.some(row=>row.product_catalog_id === chosen);
  return <div className="pending-cost-review" aria-label={`Επιβεβαίωση γραμμής ${line.line_number}`}>
    <div className="pending-cost-search">
      <label><span><Search size={15}/>Αναζήτηση προϊόντος INDE</span><input type="search" aria-label="Αναζήτηση προϊόντος INDE" value={query} maxLength={200}
        disabled={saving} onChange={event=>{setQuery(event.target.value);setChosen("");setConfirmed(false);}}/></label>
      <label><span>Προϊόν INDE</span><select aria-label="Προϊόν INDE" value={chosen} disabled={saving} onChange={event=>{setChosen(event.target.value);setConfirmed(false);}}>
        <option value="">{searching ? "Αναζήτηση..." : "Επιλογή προϊόντος"}</option>
        {originalChosen && <option value={chosen}>{line.inde_sku || chosen}</option>}
        {candidates.map(row=><option key={row.product_catalog_id} value={row.product_catalog_id}>{row.sku || row.model || "-"} · {row.name}</option>)}
      </select></label>
    </div>
    {chosen && <div className="pending-cost-selected">{candidates.find(row=>row.product_catalog_id === chosen)?.name || line.inde_sku}</div>}
    {!searching && query.trim().length >= 2 && !candidates.length && <div role="status">Δεν βρέθηκε προϊόν INDE.</div>}
    <div className="pending-cost-values"><span>Ποσότητα: <strong>{line.quantity ?? "-"}</strong></span><span>Καθαρή αξία γραμμής: <strong>{money(line.net_value)}</strong></span>
      <span>Κόστος / μονάδα τιμολογίου: <strong>{money(line.invoice_unit_cost_net)}</strong></span></div>
    {missingUnit && <label className="pending-cost-check"><input type="checkbox" checked={units} disabled={saving} onChange={event=>{setUnits(event.target.checked);setConfirmed(false);}}/>Η μονάδα που λείπει είναι φυσικό τεμάχιο.</label>}
    <label className="pending-cost-check"><input type="checkbox" checked={remember} disabled={!line.item_code || saving} onChange={event=>setRemember(event.target.checked)}/>Ίδιος κωδικός προμηθευτή → ίδιο προϊόν στα επόμενα τιμολόγια.</label>
    <label className="pending-cost-check"><input type="checkbox" checked={confirmed} disabled={saving || !chosen} onChange={event=>setConfirmed(event.target.checked)}/>Επιβεβαιώνω το προϊόν και ότι 1 μονάδα αγοράς = 1 φυσικό τεμάχιο.</label>
    {error && <div className="notice" role="alert">{error}</div>}
    <button className="primary-action compact" disabled={saving || !chosen || !confirmed || (missingUnit && !units)} onClick={save}><Check size={16}/>{saving ? "Αποθήκευση..." : "Επιβεβαίωση κόστους"}</button>
  </div>;
}

export function PendingSupplierCosts({start, end, supplierCode, revision, onSaved}: {
  start: string; end: string; supplierCode?: string; revision: number; onSaved: () => void;
}) {
  const [suppliers, setSuppliers] = useState<SupplierIdentity[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<PendingCostResult | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [ready, setReady] = useState(false);
  const [updated, setUpdated] = useState(false);
  const version = useRef(0);
  useEffect(() => {
    let cancelled = false;
    api.supplierIdentities().then(response=>{
      if (cancelled) return;
      setSuppliers(response.data.rows); setSupplierId(response.data.rows.find(row=>row.code === supplierCode)?.id || "");setReady(true);
    }).catch(err=>{if (!cancelled) setError(err instanceof Error ? err.message : "Δεν φορτώθηκαν οι προμηθευτές.");});
    return () => {cancelled = true;};
  }, [supplierCode]);
  async function load() {
    const id = ++version.current;
    setLoading(true); setError("");
    try {
      if (!start || !end || start > end) throw new Error("Επίλεξε έγκυρη περίοδο.");
      const response = await api.pendingSupplierCosts({date_from:start, date_to:end, offset:String(offset), limit:"10", ...(supplierId ? {supplier_id:supplierId} : {})});
      if (id === version.current) {setResult(response.data);setOpen({});setUpdated(false);}
    } catch (err) {if (id === version.current) {setResult(null);setError(err instanceof Error ? err.message : "Δεν φορτώθηκαν οι εκκρεμότητες.");}}
    finally {if (id === version.current) setLoading(false);}
  }
  useEffect(()=>{setOffset(0);setMessage("");},[start,end,supplierId]);
  useEffect(()=>{if (ready) load();return()=>{version.current++;};},[start,end,supplierId,offset,ready]);
  useEffect(()=>{
    if (!ready) return;
    if (Object.values(open).some(Boolean)) setUpdated(true); else load();
  },[revision]);
  function saved() {setMessage("Το κόστος επιβεβαιώθηκε από τη γραμμή της ΑΑΔΕ."); if (offset) setOffset(0); else load(); onSaved();}
  const rows = (result?.invoices || []).flatMap<Row>(invoice=>invoice.lines.length ? invoice.lines.map(line=>({key:`${invoice.id}:${invoice.supplier_id}:${line.line_number}`,invoice,line})) : [{key:`${invoice.id}:${invoice.supplier_id}`,invoice,line:null}]);
  const columns: Column<Row>[] = [
    {key:"supplier",header:"Προμηθευτής",render:({invoice})=><div className="supplier-catalog-stack">{invoice.supplier}<small>{invoice.issuer_vat}</small></div>},
    {key:"invoice",header:"Τιμολόγιο ΑΑΔΕ",render:({invoice})=><div className="supplier-catalog-stack"><a href={invoiceLink(invoice.id)} target="_blank" rel="noopener noreferrer">{invoice.number} <ExternalLink size={13}/></a><small>{invoice.date}</small></div>},
    {key:"product",header:"Προϊόν τιμολογίου",render:({line})=><div className="supplier-catalog-stack"><strong>{line?.item_code || "Χωρίς κωδικό"}</strong><span>{line?.description || "Δεν υπάρχουν αναλυτικές γραμμές προϊόντων."}</span></div>},
    {key:"quantity",header:"Ποσότητα",align:"right",render:({line})=>line?.quantity ?? "-"},
    {key:"net",header:"Αξία χωρίς ΦΠΑ",align:"right",render:({line})=>money(line?.net_value ?? null)},
    {key:"unit",header:"Κόστος / μονάδα",align:"right",render:({line})=>money(line?.invoice_unit_cost_net ?? null)},
    {key:"reason",header:"Εκκρεμότητα",render:({invoice,line})=><div className="pending-cost-reasons">{[...invoice.reasons,...(line?.reasons || [])].map((value,index)=><span key={index}>{reason(value)}</span>)}{line && !invoice.reasons.length && !line.reasons.length && <span>Έτοιμο για επιβεβαίωση.</span>}</div>},
    {key:"review",header:"",render:row=><button className="icon-button" title="Επιβεβαίωση προϊόντος" aria-label={`Επιβεβαίωση ${row.line?.item_code || row.invoice.number}`}
      disabled={!row.line || Boolean(row.invoice.reasons.length) || row.line.reasons.includes("Special fiscal line (fee / tax / adjustment) requires separate review.")}
      aria-expanded={Boolean(open[row.key])} onClick={()=>setOpen(current=>({...current,[row.key]:!current[row.key]}))}>
      {open[row.key] ? <ChevronUp size={17}/> : <ChevronDown size={17}/>}</button>},
  ];
  return <section className="pending-costs" aria-label="Εκκρεμείς κοστολογήσεις">
    <div className="pending-cost-toolbar"><label><span>Προμηθευτής</span><select aria-label="Προμηθευτής εκκρεμοτήτων" value={supplierId} onChange={event=>setSupplierId(event.target.value)}>
      <option value="">Όλοι οι προμηθευτές</option>{suppliers.filter(row=>row.id).map(row=><option key={row.id} value={row.id!}>{row.name}</option>)}
    </select></label><button className="secondary-action compact" disabled={loading || !ready} onClick={load}><RefreshCw size={16}/>Ανανέωση</button></div>
    {message && <div role="status" className="notice">{message}</div>}
    {updated && <div role="status" className="notice">Υπάρχουν νέες ενημερώσεις. Ανανέωσε τη λίστα πριν επιβεβαιώσεις.</div>}
    {error && <div role="alert" className="notice">{error}</div>}
    <div aria-busy={loading}><DataTable rows={loading ? [] : rows} columns={columns} rowKey={row=>row.key}
      empty={loading || !ready ? "Φόρτωση εκκρεμών κοστολογήσεων..." : "Δεν υπάρχουν εκκρεμείς κοστολογήσεις στην περίοδο."}
      renderExpandedRow={row=>row.line && open[row.key] ? <LineReview invoice={row.invoice} line={row.line} onSaved={saved}/> : null}/></div>
    <div className="supplier-catalog-pagination"><button className="icon-button" aria-label="Προηγούμενα τιμολόγια" title="Προηγούμενα τιμολόγια" disabled={loading || !offset} onClick={()=>setOffset(Math.max(0,offset-10))}><ChevronLeft size={17}/></button>
      <span>Τιμολόγια {result?.total ? `${offset+1}–${Math.min(offset+10,result.total)} / ${result.total}` : "0"}</span>
      <button className="icon-button" aria-label="Επόμενα τιμολόγια" title="Επόμενα τιμολόγια" disabled={loading || !result || offset+10>=result.total} onClick={()=>setOffset(offset+10)}><ChevronRight size={17}/></button></div>
  </section>;
}
