import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw, X } from "lucide-react";
import { api } from "../api/client";
import type { SupplierCatalogInvoices, SupplierCatalogProduct } from "../api/client";
import { invoiceLink } from "../utils/recordLinks";
import { DataTable } from "./DataTable";

const currency = new Intl.NumberFormat("el-GR", {style:"currency", currency:"EUR", maximumFractionDigits:4});
export function SupplierProductInvoices({product, onClose}: {product: SupplierCatalogProduct; onClose:()=>void}) {
  const [data, setData] = useState<SupplierCatalogInvoices | null>(null);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState("");
  useEffect(()=>{
    let active = true;
    setData(null); setError("");
    api.supplierCatalogInvoices(product.id, offset).then(result=>{if(active) setData(result);})
      .catch(err=>{if(active) setError(err instanceof Error ? err.message : "Could not load invoices.");});
    return ()=>{active=false;};
  },[product.id, offset, retry]);
  return <section className="supplier-product-orders" id={`product-invoices-${product.id}`} aria-label={`AADE invoices for ${product.supplier_code}`}>
    <div className="panel-title"><h2>AADE invoices / {product.supplier_code}</h2>
      <button className="icon-button" title="Close invoices" aria-label={`Close invoices ${product.supplier_code}`} onClick={onClose}><X size={17}/></button></div>
    <p>Verified purchase cost history{data ? ` | Invoices: ${data.total}` : ""}</p>
    {error ? <div className="notice" role="alert">{error}<button className="icon-button" title="Retry invoices" aria-label="Retry invoices" onClick={()=>setRetry(value=>value+1)}><RefreshCw size={16}/></button></div>
      : !data ? <p role="status">Loading AADE invoices...</p> : <>
      <DataTable rows={data.rows} rowKey={row=>row.document_id} empty="No verified AADE purchase invoices for this product." columns={[
        {key:"date",header:"Invoice date",render:row=>row.date},
        {key:"invoice",header:"Invoice",render:row=><a className="record-link" href={invoiceLink(row.document_id)} target="_blank" rel="noopener noreferrer" title="Open AADE invoice in new tab">{row.number || row.mark}</a>},
        {key:"mark",header:"AADE MARK",render:row=>row.mark},
        {key:"qty",header:"Purchased pieces",align:"right",render:row=>Number(row.quantity).toLocaleString("el-GR")},
        {key:"cost",header:"Net cost / piece",align:"right",render:row=>row.unit_cost_min === row.unit_cost_max ? currency.format(Number(row.unit_cost_min)) : `${currency.format(Number(row.unit_cost_min))} - ${currency.format(Number(row.unit_cost_max))}`},
        {key:"current",header:"Catalog cost",render:row=>row.current ? <strong>Current price source</strong> : "-"},
      ]}/>
      {data.total>50 && <div className="supplier-catalog-pagination">
        <button className="icon-button" title="Previous invoices page" aria-label="Previous invoices page" disabled={!offset} onClick={()=>setOffset(value=>value-50)}><ChevronLeft size={17}/></button>
        <span>{offset+1}-{Math.min(offset+50,data.total)} / {data.total}</span>
        <button className="icon-button" title="Next invoices page" aria-label="Next invoices page" disabled={offset+50>=data.total} onClick={()=>setOffset(value=>value+50)}><ChevronRight size={17}/></button>
      </div>}
    </>}
  </section>;
}
