import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw, X } from "lucide-react";
import { api } from "../api/client";
import type { SupplierCatalogOrders, SupplierCatalogProduct } from "../api/client";
import { DataTable } from "./DataTable";

export function SupplierProductOrders({ product, start, end, onClose }: {
  product: SupplierCatalogProduct; start: string; end: string; onClose: () => void;
}) {
  const [data, setData] = useState<SupplierCatalogOrders | null>(null);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  useEffect(() => {
    const id = ++requestId.current;
    setLoading(true); setError(""); setData(null);
    if (!start || !end || start > end) {
      setError("Select a valid From / To period."); setLoading(false); return;
    }
    api.supplierCatalogOrders(product.id, {date_from: start, date_to: end, offset: String(offset), limit: "50"})
      .then(result => { if (id === requestId.current) setData(result); })
      .catch(err => { if (id === requestId.current) setError(err instanceof Error ? err.message : "Could not load orders."); })
      .finally(() => { if (id === requestId.current) setLoading(false); });
    return () => { requestId.current++; };
  }, [product.id, start, end, offset, retry]);

  return <section className="supplier-product-orders" id={`product-orders-${product.id}`}
    aria-label={`INDE orders for ${product.supplier_code}`} aria-busy={loading}>
    <div className="panel-title"><h2>INDE orders / {product.supplier_code}</h2>
      <button className="icon-button" title="Close orders" aria-label={`Close orders ${product.supplier_code}`} onClick={onClose}><X size={17}/></button></div>
    <p>{start} - {end}{data ? ` | Orders: ${data.total}` : ""}</p>
    {error && <div className="notice" role="alert">{error}<button className="icon-button" title="Retry orders" aria-label={`Retry orders ${product.supplier_code}`} onClick={()=>setRetry(value=>value+1)}><RefreshCw size={16}/></button></div>}
    {loading ? <p role="status">Loading INDE orders...</p> : data && <>
      <DataTable rows={data.rows} rowKey={row=>row.order_id} empty={data.match_status !== "matched"
        ? "No confirmed INDE product match." : "No stored orders for this product in the selected period."} columns={[
        {key:"order", header:"INDE order", render:row=><strong>{row.order_id}</strong>},
        {key:"date", header:"Order date", render:row=>new Date(row.date_added).toLocaleString("el-GR")},
        {key:"status", header:"Current status", render:row=>row.order_status || "-"},
        {key:"quantity", header:"Product quantity", align:"right", render:row=>row.quantity},
      ]}/>
      {data.total > 50 && <div className="supplier-catalog-pagination">
        <button className="icon-button" title="Previous orders page" aria-label={`Previous orders page ${product.supplier_code}`} disabled={offset === 0} onClick={()=>setOffset(value=>Math.max(0,value-50))}><ChevronLeft size={17}/></button>
        <span>{`${Math.min(offset+1,data.total)}-${Math.min(offset+50,data.total)} / ${data.total}`}</span>
        <button className="icon-button" title="Next orders page" aria-label={`Next orders page ${product.supplier_code}`} disabled={offset+50>=data.total} onClick={()=>setOffset(value=>value+50)}><ChevronRight size={17}/></button>
      </div>}
    </>}
  </section>;
}
