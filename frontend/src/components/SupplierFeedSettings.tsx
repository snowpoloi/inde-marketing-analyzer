import { useEffect, useState } from "react";
import { Plus, RefreshCw, Save } from "lucide-react";
import { api } from "../api/client";
import type { SupplierCatalogFeed } from "../api/client";

export function SupplierFeedSettings() {
  const [feeds, setFeeds] = useState<SupplierCatalogFeed[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("MEGAPAP");
  const [code, setCode] = useState("MEGAPAP");
  const [url, setUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [hours, setHours] = useState(24);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const current = feeds.find(feed => feed.id === selected);

  async function load() { const rows = await api.supplierCatalogFeeds(); setFeeds(rows); return rows; }
  useEffect(() => { load().catch(err => setMessage(err.message)); }, []);

  function select(id: string, rows = feeds) {
    const feed = rows.find(item => item.id === id);
    setSelected(id); setUrl(""); setMessage("");
    setName(feed?.name || "MEGAPAP"); setCode(feed?.code || "MEGAPAP");
    setEnabled(feed?.is_enabled ?? true); setHours(feed?.refresh_hours || 24);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const feed = await api.saveSupplierCatalogFeed(selected || null, {
        code, name, adapter: "megapap", ...(url.trim() ? { url: url.trim() } : {}), is_enabled: enabled, refresh_hours: hours
      });
      const rows = await load(); select(feed.id, rows); setMessage("Supplier XML saved.");
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
      <button className="icon-button" title="Add supplier feed" aria-label="Add supplier feed" onClick={() => select("")}><Plus size={18} /></button>
    </div>
    {message && <div className="notice" role="status">{message}</div>}
    <form onSubmit={save}>
      <div className="form-grid">
        <label><span>Supplier feed</span><select aria-label="Supplier feed" value={selected} onChange={event => select(event.target.value)}>
          <option value="">New feed</option>{feeds.map(feed => <option value={feed.id} key={feed.id}>{feed.name}</option>)}
        </select></label>
        <label><span>XML format</span><select aria-label="XML format" value="megapap" disabled><option value="megapap">MEGAPAP</option></select></label>
        <label><span>Supplier name</span><input value={name} maxLength={255} required onChange={event => setName(event.target.value)} /></label>
        <label><span>Supplier code</span><input value={code} maxLength={120} pattern="[A-Za-z0-9_-]+" required onChange={event => setCode(event.target.value)} /></label>
        <label className="form-grid-span"><span>Private XML URL</span><input type="password" autoComplete="new-password" value={url}
          required={!current?.configured} placeholder={current?.configured ? "Saved URL retained" : "https://www.megapap.com/..."}
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
  </section>;
}
