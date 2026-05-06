import { FormEvent, useEffect, useState } from "react";
import { Play, Upload } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import type { SyncRun } from "../api/client";
import type { Column } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";

const providers = ["meta_ads", "google_ads", "ga4", "merchant_center", "opencart", "shoply"];

function isoDate(daysOffset = 0) {
  const value = new Date();
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString().slice(0, 10);
}

export function SyncLogsPage() {
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [dateTo, setDateTo] = useState(isoDate());
  const [dateFrom, setDateFrom] = useState(isoDate(-1));
  const [selectedProviders, setSelectedProviders] = useState(providers);
  const [googleFile, setGoogleFile] = useState<File | null>(null);
  const [metaFile, setMetaFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    setRuns(await api.syncRuns());
  }

  useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : "Could not load sync logs"));
  }, []);

  async function trigger() {
    setMessage("");
    await api.triggerSync(selectedProviders, dateFrom, dateTo);
    await load();
  }

  async function importFile(event: FormEvent, kind: "google" | "meta") {
    event.preventDefault();
    const file = kind === "google" ? googleFile : metaFile;
    if (!file) {
      setMessage("Select a CSV file first.");
      return;
    }
    await api.importCsv(kind, dateTo, file);
    setMessage(`${file.name} imported.`);
    await load();
  }

  const columns: Column<SyncRun>[] = [
    { key: "provider", header: "Provider", render: (row) => row.provider },
    { key: "type", header: "Type", render: (row) => row.sync_type },
    { key: "status", header: "Status", render: (row) => <StatusBadge value={row.status} /> },
    { key: "period", header: "Period", render: (row) => `${row.date_from ?? "-"} to ${row.date_to ?? "-"}` },
    { key: "records", header: "Records", align: "right", render: (row) => row.records_processed },
    { key: "started", header: "Started", render: (row) => new Date(row.started_at).toLocaleString("el-GR") },
    { key: "error", header: "Error", render: (row) => row.error_message || "-" }
  ];

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1>Sync logs</h1>
          <p>Daily worker runs, manual syncs, and CSV imports.</p>
        </div>
      </header>
      {message ? <div className="notice">{message}</div> : null}

      <section className="panel">
        <div className="panel-title">
          <h2>Manual sync</h2>
          <span>Read-only provider pull</span>
        </div>
        <div className="sync-controls">
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          <div className="provider-pills">
            {providers.map((provider) => (
              <label key={provider}>
                <input
                  type="checkbox"
                  checked={selectedProviders.includes(provider)}
                  onChange={() =>
                    setSelectedProviders((current) =>
                      current.includes(provider) ? current.filter((item) => item !== provider) : [...current, provider]
                    )
                  }
                />
                {provider}
              </label>
            ))}
          </div>
          <button className="primary-action compact" onClick={trigger}>
            <Play size={17} />
            Run sync
          </button>
        </div>
      </section>

      <div className="two-column">
        <form className="panel import-panel" onSubmit={(event) => importFile(event, "google")}>
          <div className="panel-title">
            <h2>Google Ads CSV</h2>
            <span>campaign_name, cost, clicks, conversions...</span>
          </div>
          <input type="file" accept=".csv,text/csv" onChange={(event) => setGoogleFile(event.target.files?.[0] ?? null)} />
          <button className="primary-action compact">
            <Upload size={17} />
            Import
          </button>
        </form>
        <form className="panel import-panel" onSubmit={(event) => importFile(event, "meta")}>
          <div className="panel-title">
            <h2>Meta Ads CSV</h2>
            <span>date, campaign, adset, ad, spend...</span>
          </div>
          <input type="file" accept=".csv,text/csv" onChange={(event) => setMetaFile(event.target.files?.[0] ?? null)} />
          <button className="primary-action compact">
            <Upload size={17} />
            Import
          </button>
        </form>
      </div>

      <section className="panel">
        <div className="panel-title">
          <h2>Run history</h2>
          <span>Latest 100 entries</span>
        </div>
        <DataTable rows={runs} columns={columns} empty="No sync runs yet." />
      </section>
    </div>
  );
}
