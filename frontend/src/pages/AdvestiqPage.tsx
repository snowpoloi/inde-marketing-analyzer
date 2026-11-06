import { useEffect, useState } from "react";
import { RefreshCw, Zap } from "lucide-react";
import { api } from "../api/client";
import type { AdvestiqReport, AdvestiqReportKind, AdvestiqReportSummary, SyncFreshness } from "../api/client";
import { MarkdownView } from "../components/MarkdownView";
import "../styles/advestiq.css";

const dateLabel = new Intl.DateTimeFormat("el-GR", { weekday: "short", day: "numeric", month: "numeric", year: "numeric" });

function formatDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return dateLabel.format(new Date(year, month - 1, day));
}

function formatTime(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("el-GR", { hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(value));
}

// Today's sources: the intraday providers that are switched on.
function todayProviders(freshness: SyncFreshness | null) {
  return (freshness?.providers ?? []).filter((row) => row.intraday && row.enabled);
}

export function AdvestiqPage() {
  const [kind, setKind] = useState<AdvestiqReportKind>("daily");
  const [rows, setRows] = useState<AdvestiqReportSummary[]>([]);
  const [selected, setSelected] = useState<AdvestiqReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [freshness, setFreshness] = useState<SyncFreshness | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState("");

  async function open(id: string) {
    try {
      setSelected((await api.advestiqReport(id)).data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function load(nextKind: AdvestiqReportKind) {
    setLoading(true);
    setError("");
    try {
      const result = await api.advestiqReports(nextKind);
      setRows(result.data.rows);
      if (result.data.rows[0]) await open(result.data.rows[0].id);
      else setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadFreshness() {
    try {
      setFreshness((await api.syncFreshness()).data);
    } catch {
      setFreshness(null);
    }
  }

  // Runs today's sync for the intraday sources through the normal admin sync (POST /api/sync/run).
  async function syncToday() {
    const providers = todayProviders(freshness);
    if (!freshness || providers.length === 0) {
      setSyncNotice("Δεν υπάρχουν ενεργές πηγές για ενημέρωση.");
      return;
    }
    setSyncing(true);
    setSyncNotice("Ενημέρωση σε εξέλιξη. Μπορεί να πάρει 1–2 λεπτά.");
    try {
      const runs = await api.triggerSync(providers.map((row) => row.provider), freshness.today, freshness.today);
      const names = new Map(providers.map((row) => [row.provider, row.name]));
      const failed = runs.filter((run) => run.status !== "success").map((run) => names.get(run.provider) ?? run.provider);
      setSyncNotice(failed.length
        ? `Ενημερώθηκαν ${runs.length - failed.length} από ${runs.length}. Χωρίς ενημέρωση: ${failed.join(", ")}. Δες τις καταγραφές συγχρονισμού.`
        : `Ενημερώθηκαν και οι ${runs.length} πηγές.`);
    } catch (err) {
      setSyncNotice(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
      await loadFreshness();
    }
  }

  useEffect(() => {
    void load(kind);
  }, [kind]);

  useEffect(() => {
    void loadFreshness();
  }, []);

  const sources = todayProviders(freshness);

  return (
    <div className="page-stack advestiq-page">
      <header className="page-header">
        <div>
          <h1>ADVESTIQ</h1>
          <p>Οι αναφορές του διαφημιστικού γραφείου. Μόνο ανάγνωση και προτάσεις, καμία αλλαγή στους λογαριασμούς.</p>
        </div>
        <div className="advestiq-actions">
          <div className="advestiq-kinds">
            <button className={kind === "daily" ? "active" : ""} onClick={() => setKind("daily")}>Πρωινές</button>
            <button className={kind === "weekly" ? "active" : ""} onClick={() => setKind("weekly")}>Εβδομαδιαίες</button>
          </div>
          <button onClick={() => void load(kind)} disabled={loading}><RefreshCw size={16} />Ανανέωση</button>
          <button onClick={() => void syncToday()} disabled={syncing || !freshness || sources.length === 0}
            title="Φέρνει τα σημερινά νούμερα από διαφημίσεις, παραγγελίες και GA4.">
            <Zap size={16} />{syncing ? "Ενημέρωση…" : "Ενημέρωση σήμερα"}
          </button>
        </div>
      </header>
      {freshness && sources.length > 0 ? (
        <p className="advestiq-freshness">
          Σήμερα: {sources.map((row) => `${row.name} ${row.today_synced_at ? formatTime(row.today_synced_at, freshness.timezone) : "—"}`).join(" · ")}
          {freshness.intraday.next_run_at ? ` · Επόμενη αυτόματη ενημέρωση ${formatTime(freshness.intraday.next_run_at, freshness.timezone)}` : ""}
        </p>
      ) : null}
      {syncNotice ? <div className="notice" role="status">{syncNotice}</div> : null}
      {error ? <div className="notice">{error}</div> : null}
      <div className="advestiq-layout">
        <aside className="advestiq-list panel">
          {rows.length === 0 && !loading ? <p className="advestiq-empty">Δεν υπάρχουν ακόμα αναφορές.</p> : null}
          {rows.map((row) => (
            <button key={row.id} className={selected?.id === row.id ? "active" : ""} onClick={() => void open(row.id)}>
              <strong>{formatDate(row.report_date)}</strong>
              <span>{row.title}</span>
              {row.summary ? <small>{row.summary}</small> : null}
            </button>
          ))}
        </aside>
        <article className="advestiq-report panel">
          {selected ? <MarkdownView source={selected.markdown} /> : <p className="advestiq-empty">Διάλεξε μια αναφορά.</p>}
        </article>
      </div>
    </div>
  );
}
