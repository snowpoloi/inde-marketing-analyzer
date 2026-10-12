import { useEffect, useRef, useState } from "react";
import { Save, Upload } from "lucide-react";
import { api } from "../api/client";
import type { ShippingSettings } from "../api/orderShipping";

export function OrderShippingSettings() {
  const [settings, setSettings] = useState<ShippingSettings | null>(null);
  const [pending, setPending] = useState<unknown>(null);
  const [filename, setFilename] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(()=>{
    let active = true;
    api.orderShippingSettings().then(result=>{if (active) setSettings(result.data);})
      .catch(err=>{if (active) setMessage(err instanceof Error ? err.message : "Could not load shipping tariffs.");});
    return ()=>{active = false;};
  }, []);
  async function importFile(selected?: File) {
    setPending(null); setFilename(""); setMessage("");
    if (!selected) return;
    if (selected.size > 5_000_000) {setMessage("Tariff file must be smaller than 5 MB."); return;}
    try {setPending(JSON.parse(await selected.text())); setFilename(selected.name);}
    catch {setMessage("Invalid tariff configuration file.");}
  }
  async function save() {
    setBusy(true); setMessage("");
    try {
      const result = await api.saveOrderShippingSettings(pending);
      setSettings(result.data); setPending(null); setFilename(""); setMessage("Shipping tariffs saved.");
    } catch (err) {setMessage(err instanceof Error ? err.message : "Could not save shipping tariffs.");}
    finally {setBusy(false);}
  }
  return <section className="panel"><div className="panel-title"><h2>Order shipping tariffs</h2>
    <span>{settings?.configured ? "Configured / Athens" : "Not configured"}</span></div>
    {settings?.configured && <dl className="shipping-breakdown"><div><dt>Mytrans</dt><dd>{settings.mytrans?.version}</dd></div>
      <div><dt>Speedex</dt><dd>{settings.speedex?.version}</dd></div><div><dt>Mytrans area records</dt><dd>{settings.mytrans_area_rows}</dd></div>
      <div><dt>Speedex area records</dt><dd>{settings.speedex_area_rows ?? 0}</dd></div>
      {settings.speedex_area_source && <div><dt>Speedex area source</dt><dd>{settings.speedex_area_source}</dd></div>}
      <div><dt>Speedex max. parcel side</dt><dd>{settings.speedex?.max_side_cm ?? "Unconfirmed"} cm</dd></div></dl>}
    <div className="sync-controls"><input ref={file} type="file" accept=".json,application/json" hidden onChange={e=>{
      importFile(e.target.files?.[0]); e.target.value = "";
    }}/><button className="secondary-action compact" disabled={busy} onClick={()=>file.current?.click()}><Upload size={17}/>Import private tariffs</button>
      {pending != null && <><span>{filename}</span><button className="primary-action compact" disabled={busy} onClick={save}><Save size={17}/>Save shipping tariffs</button></>}
    </div>{message && <div className="notice" role="status">{message}</div>}
  </section>;
}
