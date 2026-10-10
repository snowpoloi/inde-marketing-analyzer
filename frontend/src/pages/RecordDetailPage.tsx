import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { AadeDocumentDetail, StoredOrderDetail } from "../api/client";
import { DataTable } from "../components/DataTable";
import { formatAadeInvoiceType } from "../utils/aadeInvoiceTypes";

export function RecordDetailPage({kind, id, onBack}: {kind:"invoice" | "order"; id:string; onBack:()=>void}) {
  const [invoice, setInvoice] = useState<AadeDocumentDetail | null>(null);
  const [order, setOrder] = useState<StoredOrderDetail | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(()=>{
    let active=true;
    setInvoice(null); setOrder(null); setError("");
    if(kind === "invoice") api.aadeDocument(id).then(result=>{if(active) setInvoice(result.data);})
      .catch(err=>{if(active) setError(err instanceof Error ? err.message : "Could not load invoice.");});
    else api.orderDetail(id).then(result=>{if(active) setOrder(result.data);})
      .catch(err=>{if(active) setError(err instanceof Error ? err.message : "Could not load order.");});
    return ()=>{active=false;};
  },[kind,id,retry]);
  const money=(value:number | null)=>value == null ? "-" : new Intl.NumberFormat("el-GR", {style:"currency",currency:invoice?.currency || "EUR",maximumFractionDigits:4}).format(Number(value));
  const title=invoice ? `AADE / ${[invoice.series,invoice.aa].filter(Boolean).join(" / ") || invoice.mark}` : order ? `INDE order / ${order.order_id}` : kind === "invoice" ? "AADE invoice" : "INDE order";
  useEffect(()=>{document.title=title; return ()=>{document.title="INDE Marketing Analyzer";};},[title]);
  return <div className="page-stack record-detail">
    <header className="page-header"><h1>{title}</h1><button className="secondary-action compact" onClick={onBack}><ArrowLeft size={17}/>{kind === "invoice" ? "AADE" : "Orders"}</button></header>
    {error ? <div className="notice" role="alert">{error}<button className="icon-button" title="Retry" aria-label="Retry" onClick={()=>setRetry(value=>value+1)}><RefreshCw size={17}/></button></div>
      : !invoice && !order ? <p role="status">Loading {kind}...</p> : null}
    {invoice && <>
      <dl className="supplier-catalog-detail-grid">
        <div><dt>Invoice date</dt><dd>{invoice.issue_date}</dd></div>
        <div><dt>Supplier</dt><dd>{invoice.issuer_name || "-"}</dd></div>
        <div><dt>Issuer AFM</dt><dd>{invoice.issuer_vat || "-"}</dd></div>
        <div><dt>Customer AFM</dt><dd>{invoice.counterpart_vat || "-"}</dd></div>
        <div><dt>AADE MARK</dt><dd>{invoice.mark || "-"}</dd></div>
        <div><dt>Invoice type</dt><dd>{formatAadeInvoiceType(invoice.invoice_type)}</dd></div>
        <div><dt>Status</dt><dd>{invoice.is_cancelled ? "Cancelled" : "Active"}</dd></div>
        <div><dt>Net value</dt><dd>{money(invoice.net_value)}</dd></div>
        <div><dt>VAT</dt><dd>{money(invoice.vat_amount)}</dd></div>
        <div><dt>Total</dt><dd>{money(invoice.gross_value)}</dd></div>
      </dl>
      <section><h2>Invoice lines</h2><DataTable rows={invoice.line_items} empty="No stored invoice lines." columns={[
        {key:"line",header:"Line",render:row=>row.line_number || "-"},
        {key:"code",header:"Item code",render:row=>row.item_code || "-"},
        {key:"description",header:"Description",render:row=><span className="record-description">{row.description || "-"}</span>},
        {key:"qty",header:"Qty",align:"right",render:row=>row.quantity == null ? "-" : Number(row.quantity).toLocaleString("el-GR")},
        {key:"unit",header:"Unit",render:row=>row.measurement_unit || "-"},
        {key:"price",header:"Net unit price",align:"right",render:row=>money(row.unit_price)},
        {key:"net",header:"Net",align:"right",render:row=>money(row.net_value)},
        {key:"vat",header:"VAT",align:"right",render:row=>money(row.vat_amount)},
        {key:"gross",header:"Total",align:"right",render:row=>money(row.gross_value)},
      ]}/></section>
    </>}
    {order && <>
      <dl className="supplier-catalog-detail-grid">
        <div><dt>Order date</dt><dd>{new Date(order.date_added).toLocaleString("el-GR")}</dd></div>
        <div><dt>Status</dt><dd>{order.status || "-"}</dd></div>
        <div><dt>Payment method</dt><dd>{order.payment_method || "-"}</dd></div>
        <div><dt>Shipping method</dt><dd>{order.shipping_method || "-"}</dd></div>
        <div><dt>Subtotal</dt><dd>{money(order.sub_total)}</dd></div>
        <div><dt>Shipping</dt><dd>{money(order.shipping)}</dd></div>
        <div><dt>Tax</dt><dd>{money(order.tax)}</dd></div>
        <div><dt>Total</dt><dd>{money(order.total)}</dd></div>
      </dl>
      <section><h2>Order lines</h2><DataTable rows={order.lines} empty="No stored order lines." columns={[
        {key:"name",header:"Product",render:row=><span className="record-description">{row.name}</span>},
        {key:"sku",header:"INDE SKU",render:row=>row.sku || "-"},
        {key:"model",header:"Model",render:row=>row.model || "-"},
        {key:"qty",header:"Qty",align:"right",render:row=>row.quantity},
        {key:"price",header:"Unit price",align:"right",render:row=>money(row.unit_price)},
        {key:"total",header:"Line value",align:"right",render:row=>money(row.line_total)},
      ]}/></section>
    </>}
  </div>;
}
