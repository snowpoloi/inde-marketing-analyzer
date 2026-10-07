import { useEffect, useState } from "react";
import { Plus, Save } from "lucide-react";
import { api, type SupplierIdentity } from "../api/client";

export function SupplierIdentitySettings() {
  const [rows, setRows] = useState<SupplierIdentity[]>([]);
  const [selected, setSelected] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [vat, setVat] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.supplierIdentities().then(result => setRows(result.data.rows)).catch(err => setError(err.message)); }, []);
  function choose(value: string, options = rows) {
    const row = options.find(row => row.code === value);
    setSelected(value); setCode(row?.code || ""); setName(row?.name || ""); setVat(row?.vat_number || "");
    setMessage(""); setError("");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.saveSupplierIdentity({code, name, vat_number:vat});
      const options = [...rows.filter(row => row.code !== result.data.code), result.data]
        .sort((a, b) => a.name.localeCompare(b.name));
      setRows(options); choose(result.data.code, options); setMessage("Supplier AFM and company name saved.");
    } catch (err) { setError(err instanceof Error ? err.message : "Supplier could not be saved."); }
    finally { setBusy(false); }
  }
  return <section className="supplier-feed-settings" aria-label="Supplier identities">
    <div className="panel-title"><h2>Supplier identities</h2>
      <button className="icon-button" aria-label="Add supplier identity" title="Add supplier identity" onClick={() => choose("")} disabled={busy}><Plus size={18}/></button>
    </div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {message && <div className="notice success" role="status">{message}</div>}
    <form onSubmit={save}><div className="form-grid">
      <label><span>Supplier</span><select aria-label="Supplier identity" value={selected} disabled={busy} onChange={event => choose(event.target.value)}>
        <option value="">New supplier</option>{rows.map(row => <option key={row.code} value={row.code}>{row.name} · {row.vat_number || "AFM pending"}</option>)}
      </select></label>
      <label><span>Supplier code</span><input required maxLength={120} pattern="[A-Za-z0-9_-]+" value={code} disabled={busy || Boolean(selected)} onChange={event => setCode(event.target.value)}/></label>
      <label><span>Company name</span><input required maxLength={255} value={name} disabled={busy} onChange={event => setName(event.target.value)}/></label>
      <label><span>Supplier AFM</span><input required inputMode="numeric" maxLength={32} value={vat} disabled={busy} onChange={event => setVat(event.target.value)}/></label>
    </div><button type="submit" className="primary-action compact" disabled={busy}><Save size={16}/>Save supplier</button></form>
  </section>;
}
