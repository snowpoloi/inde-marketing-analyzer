import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { AdvestiqReport, AdvestiqReportKind, AdvestiqReportSummary } from "../api/client";
import { MarkdownView } from "../components/MarkdownView";
import "../styles/advestiq.css";

const dateLabel = new Intl.DateTimeFormat("el-GR", { weekday: "short", day: "numeric", month: "numeric", year: "numeric" });

function formatDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return dateLabel.format(new Date(year, month - 1, day));
}

export function AdvestiqPage() {
  const [kind, setKind] = useState<AdvestiqReportKind>("daily");
  const [rows, setRows] = useState<AdvestiqReportSummary[]>([]);
  const [selected, setSelected] = useState<AdvestiqReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  useEffect(() => {
    void load(kind);
  }, [kind]);

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
        </div>
      </header>
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
