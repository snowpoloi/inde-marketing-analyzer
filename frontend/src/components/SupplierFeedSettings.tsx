import { useEffect, useState } from "react";
import { Plus, RefreshCw, Save } from "lucide-react";
import { api } from "../api/client";
import type { SupplierCatalogFeed, SupplierIdentity, SupplierCatalogPricing } from "../api/client";

export function SupplierFeedSettings() {
  const [feeds, setFeeds] = useState<SupplierCatalogFeed[]>([]);
  const [identities, setIdentities] = useState<SupplierIdentity[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("MEGAPAP");
  const [code, setCode] = useState("MEGAPAP");
  const [adapter, setAdapter] = useState("megapap");
  const [url, setUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [hours, setHours] = useState(24);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [pricing, setPricing] = useState<SupplierCatalogPricing | null>(null);
  const current = feeds.find(feed => feed.id === selected);

  async function load() { const rows = await api.supplierCatalogFeeds(); setFeeds(rows); return rows; }
  useEffect(() => { load().catch(err => setMessage(err.message)); }, []);
  useEffect(() => { api.supplierIdentities().then(result => setIdentities(result.data.rows)).catch(err => setMessage(err.message)); }, []);
  useEffect(() => { api.supplierCatalogPricing().then(setPricing).catch(err => setMessage(err.message)); }, []);

  function select(id: string, rows = feeds) {
    const feed = rows.find(item => item.id === id);
    setSelected(id); setUrl(""); setMessage("");
    setName(feed?.name || "MEGAPAP"); setCode(feed?.code || "MEGAPAP");
    setAdapter(feed?.adapter || "megapap");
    setEnabled(feed?.is_enabled ?? true); setHours(feed?.refresh_hours || 24);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const feed = await api.saveSupplierCatalogFeed(selected || null, {
        code, name, adapter, ...(url.trim() ? { url: url.trim() } : {}), is_enabled: enabled, refresh_hours: hours
      });
      const rows = [...feeds.filter(row => row.id !== feed.id), feed];
      setFeeds(rows); select(feed.id, rows); setMessage("Supplier XML saved.");
    } catch (err) { setMessage(err instanceof Error ? err.message : "Could not save supplier XML."); }
    finally { setBusy(false); }
  }

  async function sync() {
    setBusy(true); setMessage("");
    try { await api.syncSupplierCatalog(selected); await load(); setMessage("Supplier sync queued."); }
    catch (err) { setMessage(err instanceof Error ? err.message : "Could not queue supplier sync."); }
    finally { setBusy(false); }
  }

  return <section className="supplier-feed-settings">
    <div className="panel-title"><h2>Supplier XML feeds</h2>
      <button className="icon-button" title="Add supplier feed" aria-label="Add supplier feed" disabled={busy} onClick={() => select("")}><Plus size={18} /></button>
    </div>
    {message && <div className="notice" role="status">{message}</div>}
    <form onSubmit={save}>
      <div className="form-grid">
        <label><span>Supplier feed</span><select aria-label="Supplier feed" value={selected} disabled={busy} onChange={event => select(event.target.value)}>
          <option value="">New feed</option>{feeds.map(feed => <option value={feed.id} key={feed.id}>{feed.name}</option>)}
        </select></label>
        <label><span>XML format</span><select aria-label="XML format" value={adapter} disabled={busy || current?.status === "running"} onChange={event => {
          setAdapter(event.target.value);
          if (!selected && !identities.some(row => row.code === code)) {
            setCode(event.target.value.toUpperCase()); setName(event.target.value === "pakoworld" ? "Pakketo AE (Pakoworld)" : "MEGAPAP");
          }
        }}><option value="megapap">MEGAPAP</option><option value="pakoworld">Pakoworld</option></select></label>
        <label className="form-grid-span"><span>Registered supplier / AFM</span><select aria-label="Registered supplier / AFM" value={identities.some(row => row.code === code) ? code : ""} disabled={busy || current?.status === "running"} onChange={event => {
          const identity = identities.find(row => row.code === event.target.value);
          setCode(identity?.code || ""); setName(identity?.name || "");
        }}><option value="">Custom supplier code</option>{identities.map(row => <option key={row.code} value={row.code}>{row.name} · {row.vat_number || "AFM pending"}</option>)}</select></label>
        <label><span>Supplier name</span><input value={name} maxLength={255} required onChange={event => setName(event.target.value)} /></label>
        <label><span>Supplier code</span><input value={code} maxLength={120} pattern="[A-Za-z0-9_-]+" required onChange={event => setCode(event.target.value)} /></label>
        <label className="form-grid-span"><span>Private XML URL</span><input type="password" autoComplete="new-password" value={url}
          required={!current?.configured} placeholder={current?.configured ? "Saved URL retained" : `https://www.${adapter}.com/...`}
          onChange={event => setUrl(event.target.value)} /></label>
        <label><span>Refresh interval (hours)</span><input type="number" min={6} max={168} value={hours} required onChange={event => setHours(Number(event.target.value))} /></label>
        <label className="supplier-feed-toggle"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Automatic XML sync</label>
      </div>
      <div className="supplier-catalog-actions">
        <button type="submit" className="primary-action compact" disabled={busy || current?.status === "running"}><Save size={16} />Save XML</button>
        {current && <button type="button" className="secondary-action compact" disabled={busy || ["queued", "running"].includes(current.status)} onClick={sync}><RefreshCw size={16} />Sync XML</button>}
        {current && <span>{current.status} · {current.counts.products ?? 0} products</span>}
      </div>
    </form>
    {current?.error && <div className="notice">{current.error}</div>}
    {pricing && <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setMessage("");
      try { setPricing(await api.saveSupplierCatalogPricing(pricing)); setMessage("Catalog cost settings saved."); }
      catch (err) { setMessage(err instanceof Error ? err.message : "Could not save cost settings."); }
      finally { setBusy(false); }
    }}>
      <h2>Catalog costs & packages</h2>
      <div className="form-grid">
        <label><span>INDE selling VAT (%)</span><input aria-label="INDE selling VAT (%)" type="number" min={0} max={100} step="0.01" value={pricing.sale_vat_rate ?? ""} onChange={event => setPricing({...pricing, sale_vat_rate: event.target.value === "" ? null : Number(event.target.value)})}/></label>
        <label><span>Volumetric divisor (cm³/kg)</span><input aria-label="Volumetric divisor" type="number" min={1000} max={10000} required value={pricing.volumetric_divisor} onChange={event => setPricing({...pricing, volumetric_divisor: Number(event.target.value)})}/></label>
        <label className="supplier-feed-toggle"><input type="checkbox" checked={pricing.automatic_costs} onChange={event => setPricing({...pricing, automatic_costs: event.target.checked})}/>Automatic AADE purchase costs</label>
      </div>
      <fieldset><legend>1 purchase unit = 1 sales unit, including invoices without unit codes</legend>
        {identities.filter(identity => identity.id && feeds.some(feed => feed.code === identity.code)).map(identity => <label className="supplier-feed-toggle" key={identity.id}>
          <input type="checkbox" checked={pricing.piece_supplier_ids.includes(identity.id!)} onChange={event => setPricing({...pricing, piece_supplier_ids: event.target.checked ? [...pricing.piece_supplier_ids, identity.id!] : pricing.piece_supplier_ids.filter(id => id !== identity.id)})}/>{identity.name}
        </label>)}
      </fieldset>
      <button className="primary-action compact" disabled={busy} type="submit"><Save size={16}/>Save cost settings</button>
    </form>}
  </section>;
}
