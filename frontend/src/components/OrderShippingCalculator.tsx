import { useEffect, useRef, useState } from "react";
import { Calculator, Plus, Trash2, X } from "lucide-react";
import { api } from "../api/client";
import type { ShippingContext, ShippingInputs, ShippingParcel, ShippingResult, ShippingValue } from "../api/orderShipping";
import "../styles/order-shipping.css";

const euros = new Intl.NumberFormat("el-GR", {style: "currency", currency: "EUR"});
const numbers = new Intl.NumberFormat("el-GR", {maximumFractionDigits: 3});
const amount = (value: ShippingValue) => value == null ? "-" : euros.format(Number(value));
const nullable = (value: string): boolean | null => value === "" ? null : value === "true";
const numeric = (value: ShippingValue) => value == null || value === "" ? null : Number(value);

function Choice({label, value, onChange, yes = "Yes", no = "No"}: {
  label: string; value: boolean | null; onChange: (value: boolean | null) => void; yes?: string; no?: string;
}) {
  return <label><span>{label}</span><select aria-label={label} value={value == null ? "" : String(value)} onChange={e=>onChange(nullable(e.target.value))}>
    <option value="">Not confirmed</option><option value="false">{no}</option><option value="true">{yes}</option>
  </select></label>;
}

export function OrderShippingCalculator({orderId, onClose}: {orderId: string; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const requestId = useRef(0);
  const [context, setContext] = useState<ShippingContext | null>(null);
  const [parcels, setParcels] = useState<ShippingParcel[]>([]);
  const [inputs, setInputs] = useState<ShippingInputs | null>(null);
  const [result, setResult] = useState<ShippingResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    dialog.current?.showModal(); close.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {document.body.style.overflow = previous;};
  }, []);

  useEffect(() => {
    const id = ++requestId.current;
    setLoading(true); setError(""); setContext(null); setInputs(null); setParcels([]); setResult(null);
    api.orderShipping(orderId).then(({data}) => {
      if (requestId.current !== id) return;
      setContext(data); setParcels(data.parcels);
      setInputs({shipping_date: data.shipping_date, manifest_confirmed: false, mytrans_zone: "", speedex_zone: "",
        mytrans_area_confirmed: false, mytrans_remote_extra: null, mytrans_cod_allowed: null,
        mytrans_local_cod: null, small_pickup: false, speedex_remote: null, saturday: false, timed: false,
        cod: null, cod_amount: data.order_total, speedex_cod_parcels: null, customer_shipping_net: null,
        ...data.defaults});
    }).catch(err => {if (requestId.current === id) setError(err instanceof Error ? err.message : "Could not load parcels.");})
      .finally(()=>{if (requestId.current === id) setLoading(false);});
    return () => {requestId.current++;};
  }, [orderId, retry]);

  function invalidate() { requestId.current++; setResult(null); setLoading(false); setError(""); }
  function matched(field: keyof ShippingInputs) {
    return Boolean(context?.matched_fields[field] && inputs && String(inputs[field]) === String(context.defaults[field]));
  }
  function update(patch: Partial<ShippingInputs>) { invalidate(); setInputs(current=>current && {...current, ...patch}); }
  function changeParcel(key: string, patch: Partial<ShippingParcel>) {
    invalidate(); setParcels(rows=>rows.map(row=>row.key === key ? {...row, ...patch} : row));
    setInputs(current=>current && {...current, manifest_confirmed: false});
  }
  async function calculate() {
    if (!inputs) return;
    const id = ++requestId.current;
    setLoading(true); setResult(null); setError("");
    try {
      const response = await api.calculateOrderShipping(orderId, {...inputs,
        mytrans_remote_extra: numeric(inputs.mytrans_remote_extra), cod_amount: numeric(inputs.cod_amount),
        customer_shipping_net: numeric(inputs.customer_shipping_net), parcels: parcels.map(row=>({...row,
          width_cm: numeric(row.width_cm), length_cm: numeric(row.length_cm), height_cm: numeric(row.height_cm), weight_kg: numeric(row.weight_kg)}))});
      if (requestId.current === id) setResult(response.data);
    } catch (err) {if (requestId.current === id) setError(err instanceof Error ? err.message : "Could not calculate shipping.");}
    finally {if (requestId.current === id) setLoading(false);}
  }

  return <dialog className="order-shipping-dialog" ref={dialog} onCancel={onClose} aria-labelledby="shipping-title">
    <header className="shipping-header"><div><h2 id="shipping-title">Shipping estimate / {orderId}</h2>
      <span>Athens departure</span></div><button ref={close} className="icon-button" onClick={onClose} title="Close shipping calculator" aria-label="Close shipping calculator"><X size={19}/></button></header>
    <div className="shipping-content" aria-busy={loading}>
      {error && <div className="notice error" role="alert">{error}{!context && <button className="secondary-action compact" onClick={()=>setRetry(value=>value+1)}>Retry</button>}</div>}
      {!context && loading && <p role="status">Loading stored order parcels...</p>}
      {context && inputs && <>
        <div className="shipping-destination"><strong>{[context.destination.city, context.destination.postcode, context.destination.region, context.destination.country].filter(Boolean).join(", ") || "Missing destination"}</strong>
          <span>{context.payment_method || "Unknown payment method"} | OpenCart shipping: {amount(context.order_shipping)} (tax basis unconfirmed)</span></div>
        {!context.settings.configured ? <div className="notice">Shipping tariffs not configured. <a href="#settings" onClick={onClose}>Open Settings</a></div> : <>
          <div className="shipping-form"><label><span>Shipping date</span><input type="date" value={inputs.shipping_date} onChange={e=>update({shipping_date:e.target.value})}/></label>
            <Choice label="Cash on delivery" value={inputs.cod} onChange={cod=>update({cod})}/>
            {inputs.cod && <><label><span>Amount to collect (EUR)</span><input type="number" min="0" step="0.01" value={inputs.cod_amount ?? ""} onChange={e=>update({cod_amount:e.target.value})}/></label>
              <label><span>Speedex COD parcels</span><input type="number" min="1" max={parcels.length} value={inputs.speedex_cod_parcels ?? ""} onChange={e=>update({speedex_cod_parcels:e.target.value ? Number(e.target.value) : null})}/></label></>}
            <label><span>Customer shipping, confirmed net (optional)</span><input type="number" min="0" step="0.01" value={inputs.customer_shipping_net ?? ""} onChange={e=>update({customer_shipping_net:e.target.value})}/></label>
          </div>
          <section className="shipping-section"><div className="panel-title"><h3>Parcels ({parcels.length})</h3>
            <button className="icon-button" title="Add actual parcel" aria-label="Add actual parcel" disabled={parcels.length >= 200} onClick={()=>{
              invalidate(); setParcels(rows=>[...rows, {key:crypto.randomUUID(), label:"Additional parcel", width_cm:null, length_cm:null, height_cm:null, weight_kg:null}]);
              setInputs(current=>current && {...current, manifest_confirmed:false});
            }}><Plus size={18}/></button></div>
            {context.warnings.length > 0 && <details><summary>Packaging checks ({context.warnings.length})</summary><ul>{context.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></details>}
            <div className="table-wrap"><table className="shipping-parcels"><thead><tr><th>Product / parcel</th><th>Width cm</th><th>Length cm</th><th>Height cm</th><th>Actual kg</th><th>m3</th><th>Vol. kg / {context.settings.volumetric_divisor}</th><th>Speedex base net</th><th>Mytrans base net</th><th></th></tr></thead>
              <tbody>{parcels.map((row,index)=>{
                const dimensions = [row.width_cm,row.length_cm,row.height_cm].map(Number);
                const cubic = dimensions.every(value=>value > 0) ? dimensions.reduce((a,b)=>a*b,1) : null;
                const limit = Number(context.settings.speedex?.max_side_cm);
                const oversized = limit > 0 && Math.max(...dimensions) > limit;
                return <tr key={row.key}><td><span className="shipping-parcel-name">{row.label}</span></td>
                  {(["width_cm","length_cm","height_cm","weight_kg"] as const).map(field=><td key={field}><input type="number" min="0.001" step="any" aria-label={`Parcel ${index+1} ${field}`} value={row[field] ?? ""} onChange={e=>changeParcel(row.key,{[field]:e.target.value})}/></td>)}
                  <td>{cubic ? numbers.format(cubic/1000000) : "-"}</td><td>{cubic ? numbers.format(cubic/(context.settings.volumetric_divisor || 5000)) : "-"}</td>
                  <td>{oversized ? <strong className="shipping-ineligible">Over {limit} cm</strong> : amount(result?.carriers.find(carrier=>carrier.carrier === "speedex")?.parcels.find(parcel=>parcel.key === row.key)?.base_net ?? null)}</td>
                  <td>{amount(result?.carriers.find(carrier=>carrier.carrier === "mytrans")?.parcels.find(parcel=>parcel.key === row.key)?.base_net ?? null)}</td>
                  <td><button className="icon-button" title="Remove parcel" aria-label={`Remove parcel ${index+1}`} onClick={()=>{
                    invalidate(); setParcels(rows=>rows.filter(item=>item.key !== row.key)); setInputs(current=>current && {...current,manifest_confirmed:false});
                  }}><Trash2 size={16}/></button></td></tr>;
              })}</tbody></table></div>
            <label className="shipping-check"><input type="checkbox" checked={inputs.manifest_confirmed} onChange={e=>update({manifest_confirmed:e.target.checked})}/>Confirmed parcel count, dimensions, actual weights and pieces per INDE sale unit</label>
          </section>
          <div className="shipping-carrier-options">
            <section className="shipping-section"><h3>Mytrans</h3><div className="shipping-form">
              <label><span>Destination zone</span><select value={inputs.mytrans_zone} onChange={e=>update({mytrans_zone:e.target.value})}><option value="">Select zone</option>{context.settings.mytrans?.zones.map(zone=><option key={zone.code} value={zone.code}>{zone.label}</option>)}</select>
                <small className="shipping-match">{matched("mytrans_zone") ? "Matched from order" : !inputs.mytrans_zone ? "Address needs a tariff zone" : "Manually selected"}</small></label>
              <label><span>Additional remote charge, net EUR</span><input type="number" min="0" step="0.01" value={inputs.mytrans_remote_extra ?? ""} onChange={e=>update({mytrans_remote_extra:e.target.value})}/></label>
              {inputs.cod && <><Choice label="COD allowed at destination" value={inputs.mytrans_cod_allowed} onChange={mytrans_cod_allowed=>update({mytrans_cod_allowed})}/>
                <Choice label="Attica / Thessaloniki COD rate" value={inputs.mytrans_local_cod} onChange={mytrans_local_cod=>update({mytrans_local_cod})}/></>}
            </div>
              {context.mytrans_areas && <details><summary>Mytrans locality matches ({context.mytrans_areas.rows.length}){context.mytrans_areas.exact_locality ? " / exact name" : " / postcode only"}</summary>
                <ul>{context.mytrans_areas.rows.map((row,index)=><li key={index}>{row.locality} / {row.municipality} / {row.status}{row.extra_net != null ? ` / +${amount(row.extra_net)}` : ""}</li>)}</ul></details>}
              <label className="shipping-check"><input type="checkbox" checked={inputs.mytrans_area_confirmed} onChange={e=>update({mytrans_area_confirmed:e.target.checked})}/>
                {matched("mytrans_area_confirmed") && matched("mytrans_remote_extra") ? "Mytrans locality and extra charge matched automatically" : "Confirmed Mytrans locality and extra remote charge"}</label>
            </section>
            <section className="shipping-section"><h3>Speedex</h3><div className="shipping-form">
              <label><span>Destination zone</span><select value={inputs.speedex_zone} onChange={e=>update({speedex_zone:e.target.value})}><option value="">Select zone</option>{context.settings.speedex?.zones.map(zone=><option key={zone.code} value={zone.code}>{zone.label}</option>)}</select>
                <small className="shipping-match">{matched("speedex_zone") ? "Matched from order" : !inputs.speedex_zone ? "Address needs a tariff zone" : "Manually selected"}</small></label>
              <Choice label="Speedex remote destination" value={inputs.speedex_remote} onChange={speedex_remote=>update({speedex_remote})}/>
            </div><label className="shipping-check"><input type="checkbox" checked={inputs.saturday} onChange={e=>update({saturday:e.target.checked})}/>Saturday delivery</label>
              <label className="shipping-check"><input type="checkbox" checked={inputs.timed} onChange={e=>update({timed:e.target.checked})}/>Timed delivery</label>
            </section>
          </div>
          {Object.keys(context.matched_fields).length > 0 && <details className="shipping-matches"><summary>Automatic order matches</summary>
            <ul>{([
              ["cod", "Cash on delivery"], ["mytrans_zone", "Mytrans zone"], ["mytrans_remote_extra", "Mytrans remote charge"],
              ["mytrans_cod_allowed", "Mytrans COD eligibility"], ["mytrans_local_cod", "Mytrans COD tariff"],
              ["speedex_zone", "Speedex zone"], ["speedex_remote", "Speedex remote classification"],
            ] as const).filter(([field])=>context.matched_fields[field]).map(([field,label])=><li key={field}><strong>{label}:</strong> {matched(field) ? context.matched_fields[field] : "Manually adjusted"}</li>)}</ul>
          </details>}
          <button className="primary-action compact" disabled={loading || parcels.length === 0 || !inputs.shipping_date} onClick={calculate}><Calculator size={17}/>{loading ? "Calculating..." : "Calculate estimate"}</button>
          {result && <div className="shipping-results" aria-live="polite">{result.carriers.map(carrier=><section key={carrier.carrier} className="shipping-section">
            <h3>{carrier.carrier === "mytrans" ? "Mytrans" : "Speedex"} <small>{carrier.status === "estimate" ? "Estimate" : carrier.status === "not_eligible" ? "Not eligible" : "Needs confirmation"}</small></h3>
            <span>{carrier.tariff_version}</span>
            {carrier.issues.length > 0 && <ul className="shipping-issues">{carrier.issues.map(issue=><li key={issue}>{issue}</li>)}</ul>}
            <dl className="shipping-breakdown">{carrier.charges.map((charge,index)=><div key={index}><dt>{charge.label}</dt><dd>{amount(charge.net)}</dd></div>)}
              <div className="shipping-total"><dt>Net</dt><dd>{amount(carrier.net)}</dd></div><div><dt>VAT ({String(context.settings.vat_percent)}%)</dt><dd>{amount(carrier.vat)}</dd></div>
              <div className="shipping-total"><dt>Total incl. VAT</dt><dd>{amount(carrier.gross)}</dd></div>
              {carrier.shipping_balance_net != null && <div><dt>Customer shipping less carrier cost (net)</dt><dd>{amount(carrier.shipping_balance_net)}</dd></div>}</dl>
            {carrier.warnings.map(warning=><p className="shipping-warning" key={warning}>{warning}</p>)}
          </section>)}</div>}
        </>}
      </>}
    </div>
  </dialog>;
}
