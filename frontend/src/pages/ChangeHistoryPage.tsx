import { useEffect, useMemo, useRef, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { BulkChangeGroup, ChangeHistory, ChangeQuery, ChangeRow } from "../api/changes";
import { NO_ACTOR } from "../api/changes";
import { MAX_CHANGE_DAYS, changePeriodRange, changePeriods, windowDays, type ChangePeriod } from "../utils/changePeriods";
import { bulkLine, changeTitle, changedValues, changesCsv, platformLabel, resourceLabel, toolLabel } from "../utils/changeText";
import "../styles/date-presets.css";
import "../styles/change-history.css";

const PAGE_SIZE = 200;
const EXPORT_LIMIT = 10_000;
const number = new Intl.NumberFormat("el-GR");
const clock = new Intl.DateTimeFormat("el-GR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Europe/Athens" });
const moment = new Intl.DateTimeFormat("el-GR", {
  day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Europe/Athens"
});
const dayTitle = new Intl.DateTimeFormat("el-GR", {
  weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC"
});

const evidenceLabels: Record<string, string> = {
  manual: "καταχωρίστηκε με το χέρι",
  email: "από email",
  export: "από αρχείο εξαγωγής"
};

function formatDay(iso: string) {
  const [year, month, day] = iso.split("-").map(Number);
  return dayTitle.format(new Date(Date.UTC(year, month - 1, day)));
}

function time(value: string) {
  return clock.format(new Date(value));
}

function plural(count: number, one: string, many: string) {
  return `${number.format(count)} ${count === 1 ? one : many}`;
}

function detailLabel(row: ChangeRow) {
  if (row.source === "google_ads") return "Πεδία που άλλαξαν";
  if (row.source === "meta_ads") return "Αφορά";
  return "Λεπτομέρειες";
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

function download(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function ChangeItem({ row }: { row: ChangeRow }) {
  const values = changedValues(row);
  const tool = toolLabel(row.client_type);
  const hasPayload = row.payload && Object.keys(row.payload).length > 0;
  return (
    <li className="change-item">
      <time dateTime={row.occurred_at}>{time(row.occurred_at)}</time>
      <div className="change-body">
        <div className="change-head">
          <span className={`change-platform source-${row.source}`}>{platformLabel(row.source)}</span>
          <strong>{changeTitle(row)}</strong>
        </div>
        <p className="change-who">
          {row.actor ?? "Χωρίς όνομα χρήστη"}
          {tool ? ` · ${tool}` : ""}
          {evidenceLabels[row.evidence_type] ? ` · ${evidenceLabels[row.evidence_type]}` : ""}
        </p>
        {row.campaign ? <p>Καμπάνια: <strong>{row.campaign}</strong></p> : null}
        {values.length ? (
          <ul className="change-values">
            {values.map((value) => <li key={value.field}><span>{value.field}:</span> {value.before} → <strong>{value.after}</strong></li>)}
          </ul>
        ) : row.detail ? <p className="change-detail">{detailLabel(row)}: {row.detail}</p> : null}
        {row.reference_url?.startsWith("https://") ? (
          <p><a href={row.reference_url} target="_blank" rel="noreferrer">Άνοιγμα της πηγής</a></p>
        ) : null}
        {hasPayload ? (
          <details className="change-raw">
            <summary>Όλα τα στοιχεία της αλλαγής</summary>
            <pre>{JSON.stringify(row.payload, null, 2)}</pre>
          </details>
        ) : null}
      </div>
    </li>
  );
}

function BulkItem({ group, minimum }: { group: BulkChangeGroup; minimum: number }) {
  const resource = resourceLabel(group.sample?.resource_type);
  const tool = toolLabel(group.sample?.client_type);
  return (
    <li className="change-item change-bulk">
      <time dateTime={group.first}>{time(group.first)}</time>
      <details className="change-body">
        <summary>
          <span className={`change-platform source-${group.source}`}>{platformLabel(group.source)}</span>
          <span>{bulkLine(group, time(group.first), time(group.last))}</span>
        </summary>
        <p className="change-who">
          Μαζικές αλλαγές: τουλάχιστον {minimum} ίδιες αλλαγές την ίδια μέρα από τον ίδιο χρήστη, συνήθως αυτόματες
          (π.χ. ανέβασμα feed).
        </p>
        {resource || tool ? <p>{[resource, tool].filter(Boolean).join(" · ")}</p> : null}
        {group.sample?.detail ? <p className="change-detail">Παράδειγμα: {group.sample.detail}</p> : null}
      </details>
    </li>
  );
}

export function ChangeHistoryPage() {
  const [period, setPeriod] = useState<ChangePeriod | "custom">("last-7");
  const [range, setRange] = useState(() => changePeriodRange("last-7"));
  const [source, setSource] = useState("");
  const [actor, setActor] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [includeBulk, setIncludeBulk] = useState(false);
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<ChangeHistory | null>(null);
  const [rows, setRows] = useState<ChangeRow[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const latest = useRef(0);

  const days = range.from && range.to ? windowDays(range.from, range.to) : 0;
  const rangeError = !range.from || !range.to ? "Διάλεξε ημερομηνίες."
    : days < 1 ? "Η ημερομηνία «έως» είναι πριν από την «από»."
      : days > MAX_CHANGE_DAYS ? `Διάλεξε έως ${MAX_CHANGE_DAYS} ημέρες (τώρα ${days}).` : "";

  const query: ChangeQuery = {
    date_from: range.from, date_to: range.to, source: source || undefined, actor: actor || undefined,
    q: q || undefined, include_bulk: includeBulk
  };

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(search.trim()), 400);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (rangeError) return;
    const id = ++latest.current;
    setLoading(true);
    setError("");
    api.changeHistory({ ...query, limit: PAGE_SIZE })
      .then((result) => {
        if (id !== latest.current) return;
        setData(result);
        setRows(result.changes);
        setHasMore(result.has_more);
      })
      .catch((err) => {
        if (id === latest.current) setError(`Δεν φορτώθηκε το ιστορικό: ${errorText(err)}`);
      })
      .finally(() => {
        if (id === latest.current) setLoading(false);
      });
  }, [range.from, range.to, source, actor, q, includeBulk, reload, rangeError]);

  async function loadMore() {
    const id = latest.current;
    setLoadingMore(true);
    try {
      const result = await api.changeHistory({ ...query, offset: rows.length, limit: PAGE_SIZE });
      if (id !== latest.current) return;
      setRows((current) => {
        const seen = new Set(current.map((row) => row.id));
        return [...current, ...result.changes.filter((row) => !seen.has(row.id))];
      });
      setHasMore(result.has_more);
    } catch (err) {
      setError(`Δεν φορτώθηκαν περισσότερες αλλαγές: ${errorText(err)}`);
    } finally {
      setLoadingMore(false);
    }
  }

  async function exportCsv() {
    setExporting(true);
    setError("");
    try {
      const all: ChangeRow[] = [];
      for (let offset = 0; offset < EXPORT_LIMIT; offset += 1000) {
        const page = await api.changeHistory({ ...query, include_bulk: false, offset, limit: 1000 });
        all.push(...page.changes);
        if (!page.has_more) break;
      }
      download(changesCsv(all, time), `allages-${range.from}-${range.to}.csv`);
    } catch (err) {
      setError(`Δεν έγινε η λήψη: ${errorText(err)}`);
    } finally {
      setExporting(false);
    }
  }

  function choosePeriod(next: ChangePeriod | "custom") {
    setPeriod(next);
    if (next !== "custom") setRange(changePeriodRange(next));
  }

  // Bulk lines for days whose changes are not loaded yet wait for "more", so each day reads in time order.
  const grouped = useMemo(() => {
    const map = new Map<string, { changes: ChangeRow[]; bulk: BulkChangeGroup[] }>();
    const entry = (day: string) => {
      if (!map.has(day)) map.set(day, { changes: [], bulk: [] });
      return map.get(day)!;
    };
    rows.forEach((row) => entry(row.day).changes.push(row));
    const oldest = rows.length ? rows[rows.length - 1].day : "";
    (data?.bulk_groups ?? []).forEach((group) => {
      if (!hasMore || !oldest || group.day >= oldest) entry(group.day).bulk.push(group);
    });
    return [...map.entries()].sort(([left], [right]) => right.localeCompare(left));
  }, [rows, data, hasMore]);

  const totals = data?.totals;
  const sources = totals?.by_source ?? [];
  const actors = totals?.by_actor ?? [];
  const coverage = (data?.coverage ?? []).filter((row) => row.days_covered < row.days_requested || row.last_fetched_at);

  return (
    <div className="page-stack change-history">
      <header className="page-header">
        <div>
          <h1>Ιστορικό αλλαγών</h1>
          <p>Τι άλλαξε στις διαφημίσεις και ποιος το άλλαξε, όπως το καταγράφουν οι ίδιες οι πλατφόρμες. Ώρα Ελλάδας.</p>
        </div>
        <div className="change-actions">
          <button className="secondary-action compact" onClick={() => setReload((value) => value + 1)} disabled={loading || Boolean(rangeError)}>
            <RefreshCw size={16} />Ανανέωση
          </button>
          <button className="secondary-action compact" onClick={() => void exportCsv()} disabled={exporting || loading || Boolean(rangeError) || !data}
            title="Οι μεμονωμένες αλλαγές με τα φίλτρα της σελίδας, σε αρχείο για Excel (έως 10.000).">
            <Download size={16} />{exporting ? "Λήψη…" : "Λήψη CSV"}
          </button>
        </div>
      </header>

      <section className="panel change-filters">
        <div className="preset-tabs change-periods" role="group" aria-label="Περίοδος">
          {changePeriods.map((item) => (
            <button key={item.key} className={`date-preset${period === item.key ? " active" : ""}`}
              aria-pressed={period === item.key} onClick={() => choosePeriod(item.key)}>{item.label}</button>
          ))}
          <button className={`date-preset${period === "custom" ? " active" : ""}`} aria-pressed={period === "custom"}
            onClick={() => choosePeriod("custom")}>Επιλογή ημερομηνιών</button>
        </div>
        {period === "custom" ? (
          <div className="change-dates">
            <label>Από<input type="date" value={range.from} max={range.to || undefined}
              onChange={(event) => setRange({ ...range, from: event.target.value })} /></label>
            <label>Έως<input type="date" value={range.to} min={range.from || undefined}
              onChange={(event) => setRange({ ...range, to: event.target.value })} /></label>
          </div>
        ) : null}
        <div className="change-filter-row">
          <label>Πλατφόρμα
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              <option value="">Όλες</option>
              {sources.map((row) => <option key={row.source} value={row.source}>{platformLabel(row.source)} ({number.format(row.count)})</option>)}
              {source && !sources.some((row) => row.source === source) ? <option value={source}>{platformLabel(source)} (0)</option> : null}
            </select>
          </label>
          <label>Ποιος έκανε την αλλαγή
            <select value={actor} onChange={(event) => setActor(event.target.value)}>
              <option value="">Όλοι</option>
              {actors.map((row) => {
                const value = row.actor ?? NO_ACTOR;
                return <option key={value} value={value}>{row.actor ?? "Χωρίς όνομα χρήστη"} ({number.format(row.count)})</option>;
              })}
              {actor && !actors.some((row) => (row.actor ?? NO_ACTOR) === actor) ? <option value={actor}>{actor === NO_ACTOR ? "Χωρίς όνομα χρήστη" : actor} (0)</option> : null}
            </select>
          </label>
          <label className="change-search">Αναζήτηση
            <input type="search" value={search} maxLength={200} placeholder="π.χ. όνομα καμπάνιας, budget, status"
              onChange={(event) => setSearch(event.target.value)} />
          </label>
          <label className="change-toggle">
            <input type="checkbox" checked={includeBulk} onChange={(event) => setIncludeBulk(event.target.checked)} />
            <span>Εμφάνιση μαζικών αυτόματων αλλαγών{data ? ` (${number.format(data.filtered.bulk)})` : ""}</span>
          </label>
        </div>
        {rangeError ? <p className="notice error" role="alert">{rangeError}</p> : null}
      </section>

      {error ? <div className="notice error" role="alert">{error}</div> : null}

      {totals ? (
        <section className="panel change-summary" aria-live="polite">
          <p className="change-total">
            <strong>{plural(totals.changes, "αλλαγή", "αλλαγές")}</strong> από {formatDay(data!.date_from)} έως {formatDay(data!.date_to)}
            <span>
              {plural(totals.individual, "μεμονωμένη", "μεμονωμένες")}
              {totals.bulk ? ` · ${plural(totals.bulk, "μαζική", "μαζικές")} σε ${plural(totals.bulk_groups, "ομάδα", "ομάδες")}` : ""}
            </span>
          </p>
          <div className="change-summary-grid">
            <div>
              <h2>Ανά πλατφόρμα</h2>
              {sources.length === 0 ? <p className="change-muted">Καμία αλλαγή.</p> : (
                <ul>
                  {sources.map((row) => (
                    <li key={row.source}>
                      <button className={source === row.source ? "active" : ""} onClick={() => setSource(source === row.source ? "" : row.source)}>
                        <span>{platformLabel(row.source)}</span>
                        <strong>{number.format(row.count)}</strong>
                      </button>
                      <small>{row.bulk ? `${number.format(row.individual)} μεμονωμένες, ${number.format(row.bulk)} μαζικές` : "όλες μεμονωμένες"}</small>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h2>Ανά άτομο</h2>
              {actors.length === 0 ? <p className="change-muted">Καμία αλλαγή.</p> : (
                <ul>
                  {actors.slice(0, 10).map((row) => {
                    const value = row.actor ?? NO_ACTOR;
                    return (
                      <li key={value}>
                        <button className={actor === value ? "active" : ""} onClick={() => setActor(actor === value ? "" : value)}>
                          <span>{row.actor ?? "Χωρίς όνομα χρήστη"}</span>
                          <strong>{number.format(row.count)}</strong>
                        </button>
                        <small>{row.sources.map(platformLabel).join(", ")}{row.bulk ? ` · ${number.format(row.bulk)} μαζικές` : ""}</small>
                      </li>
                    );
                  })}
                </ul>
              )}
              {actors.length > 10 ? <p className="change-muted">και άλλοι {actors.length - 10} στο φίλτρο «Ποιος».</p> : null}
            </div>
          </div>
          <ul className="change-notes">
            {coverage.map((row) => (
              <li key={row.source}>
                {platformLabel(row.source)}:{" "}
                {row.days_covered < row.days_requested
                  ? `ιστορικό για ${row.days_covered} από τις ${row.days_requested} ημέρες`
                  : "ιστορικό για όλες τις ημέρες"}
                {row.last_fetched_at ? ` · τελευταία λήψη ${moment.format(new Date(row.last_fetched_at))}` : ""}
                {row.days_unavailable ? ` · για ${plural(row.days_unavailable, "παλιά ημέρα", "παλιές ημέρες")} η πλατφόρμα δεν δίνει πια ιστορικό` : ""}
                {row.days_failed ? ` · η λήψη απέτυχε για ${plural(row.days_failed, "ημέρα", "ημέρες")}` : ""}
              </li>
            ))}
            <li>Ιστορικό υπάρχει μόνο για Google Ads και Meta. Για TikTok, Merchant Center και Google Tag Manager το Analyzer δεν παίρνει ιστορικό αλλαγών.</li>
          </ul>
        </section>
      ) : null}

      {data && !loading && grouped.length === 0 ? (
        <p className="panel change-muted">
          {data.filtered.bulk && !includeBulk
            ? "Καμία μεμονωμένη αλλαγή. Υπάρχουν μόνο μαζικές αυτόματες αλλαγές: άναψε την εμφάνισή τους."
            : "Καμία αλλαγή με αυτά τα φίλτρα."}
        </p>
      ) : null}
      {loading && !data ? <p className="panel change-muted">Φόρτωση…</p> : null}

      {grouped.map(([day, entry]) => (
        <section key={day} className="panel change-day">
          <h2>
            {formatDay(day)}
            <span>
              {entry.changes.length ? plural(entry.changes.length, "αλλαγή", "αλλαγές") : ""}
              {entry.changes.length && entry.bulk.length ? " · " : ""}
              {entry.bulk.length ? plural(entry.bulk.reduce((sum, group) => sum + group.count, 0), "μαζική", "μαζικές") : ""}
            </span>
          </h2>
          <ol className="change-list">
            {[...entry.bulk.map((group) => ({ at: group.last, node: <BulkItem key={`bulk-${group.source}-${group.actor}-${group.evidence_type}-${group.title}-${group.first}`}
                group={group} minimum={data?.bulk_min_size ?? 50} /> })),
              ...entry.changes.map((row) => ({ at: row.occurred_at, node: <ChangeItem key={row.id} row={row} /> }))]
              .sort((left, right) => new Date(right.at).getTime() - new Date(left.at).getTime())
              .map((item) => item.node)}
          </ol>
        </section>
      ))}

      {data ? (
        <div className="change-more">
          <span className="change-muted">
            Εμφανίζονται {number.format(rows.length)} από {plural(data.filtered.individual, "μεμονωμένη αλλαγή", "μεμονωμένες αλλαγές")}.
          </span>
          {hasMore ? (
            <button className="secondary-action compact" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore ? "Φόρτωση…" : "Περισσότερες αλλαγές"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
