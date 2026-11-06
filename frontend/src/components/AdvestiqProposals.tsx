import { useEffect, useRef, useState } from "react";
import { Check, Copy, Mail, MessageSquarePlus } from "lucide-react";
import { api } from "../api/client";
import type { Proposal, ProposalExecutor, ProposalFilter, ProposalList, ProposalPlatform, ProposalStatus } from "../api/proposals";
import { platformLabel } from "../utils/changeText";
import { proposalEmailText, proposalMailto } from "../utils/proposalEmail";
import { MarkdownView } from "./MarkdownView";
import "../styles/proposals.css";

export const proposalStatusLabels: Record<ProposalStatus, string> = {
  discussion: "Για συζήτηση",
  approved: "Εγκρίθηκε",
  sent: "Στάλθηκε στον συνεργάτη",
  done: "Έγινε",
  not_done: "Δεν έγινε",
  rejected: "Απορρίφθηκε"
};
const STATUSES: ProposalStatus[] = ["discussion", "approved", "sent", "done", "not_done", "rejected"];
const OPEN: ProposalStatus[] = ["discussion", "approved", "sent"];
const PLATFORMS: ProposalPlatform[] = ["google_ads", "meta_ads", "tiktok_ads", "merchant_center", "tracking", "site", "other"];
const executorLabels: Record<ProposalExecutor, string> = {
  agency: "Συνεργάτης",
  owner: "Ιδιοκτήτης",
  site: "Υπεύθυνος του site"
};

const dayFormat = new Intl.DateTimeFormat("el-GR", { day: "numeric", month: "numeric", year: "numeric" });
const timeFormat = new Intl.DateTimeFormat("el-GR", {
  day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  timeZone: "Europe/Athens"
});

function formatDay(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return dayFormat.format(new Date(year, month - 1, day));
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err);
}

async function copyText(value: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Falls back to the selection copy below.
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  document.body.removeChild(area);
  return copied;
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

export function AdvestiqProposals({ reloadKey, initialCode, onOpen }: {
  reloadKey: number;
  initialCode?: string;
  onOpen?: (code: string | null) => void;
}) {
  const [filter, setFilter] = useState<ProposalFilter>({ status: "", platform: "" });
  const [list, setList] = useState<ProposalList | null>(null);
  const [selected, setSelected] = useState<Proposal | null>(null);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState<"" | "done" | "failed">("");
  const wanted = useRef(initialCode ?? "");
  const detail = useRef<HTMLElement>(null);

  async function open(code: string, scroll = false) {
    setError("");
    try {
      const proposal = (await api.advestiqProposal(code)).data;
      setSelected(proposal);
      setCopied("");
      onOpen?.(proposal.code);
      if (scroll && window.matchMedia("(max-width: 860px)").matches) {
        detail.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return true;
    } catch (err) {
      setError(`Δεν άνοιξε η πρόταση ${code}: ${errorText(err)}`);
      return false;
    }
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      const result = (await api.advestiqProposals(filter)).data;
      setList(result);
      // The open proposal stays open; before any is open, a link (#advestiq/proposals/P-009) decides.
      const linked = !selected && Boolean(wanted.current);
      const keep = selected?.code ?? wanted.current;
      const next = result.rows.find((row) => row.code === keep) ?? result.rows[0];
      // A link to a proposal hidden by the filters still opens it; a link that fails shows the first one.
      if (linked && !result.rows.some((row) => row.code === keep)) {
        if (await open(keep)) return;
        wanted.current = "";
        if (next) await open(next.code);
        setError(`Δεν άνοιξε η πρόταση ${keep}. Εμφανίζεται η πρώτη της λίστας.`);
        return;
      }
      if (next) {
        await open(next.code);
      } else {
        setSelected(null);
        onOpen?.(null);
      }
    } catch (err) {
      setError(`Δεν φορτώθηκαν οι προτάσεις: ${errorText(err)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [filter.status, filter.platform, reloadKey]);

  async function refreshList() {
    try {
      setList((await api.advestiqProposals(filter)).data);
    } catch {
      // The detail is already up to date; the list catches up on the next load.
    }
  }

  async function changeStatus(status: ProposalStatus) {
    if (!selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = (await api.setAdvestiqProposalStatus(selected.code, status, comment.trim())).data;
      setSelected(updated);
      setComment("");
      setNotice(`Η πρόταση ${updated.code} είναι τώρα «${proposalStatusLabels[updated.status]}».`);
      await refreshList();
    } catch (err) {
      setError(`Δεν αποθηκεύτηκε η κατάσταση: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveComment() {
    if (!selected || !comment.trim()) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.addAdvestiqProposalNote(selected.code, comment.trim());
      setComment("");
      setSelected((await api.advestiqProposal(selected.code)).data);
      setNotice("Το σχόλιο αποθηκεύτηκε.");
      await refreshList();
    } catch (err) {
      setError(`Δεν αποθηκεύτηκε το σχόλιο: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  }

  async function copyEmail() {
    if (!selected) return;
    const done = await copyText(proposalEmailText(selected));
    setCopied(done ? "done" : "failed");
    if (done) window.setTimeout(() => setCopied((value) => (value === "done" ? "" : value)), 4000);
  }

  const counts = list?.counts;
  const total = counts ? STATUSES.reduce((sum, status) => sum + counts[status], 0) : 0;
  const openCount = counts ? OPEN.reduce((sum, status) => sum + counts[status], 0) : 0;
  const rows = list?.rows ?? [];

  return (
    <div className="proposals">
      {error ? <div className="notice error" role="alert">{error}</div> : null}
      {notice ? <div className="notice success" role="status">{notice}</div> : null}
      <div className="advestiq-layout">
        <aside className="proposal-list panel" aria-label="Λίστα προτάσεων">
          <div className="proposal-filters">
            <label>
              Κατάσταση
              <select value={filter.status} onChange={(event) => setFilter({ ...filter, status: event.target.value as ProposalFilter["status"] })}>
                <option value="">Όλες ({total})</option>
                <option value="open">Ανοιχτές ({openCount})</option>
                {STATUSES.map((status) => (
                  <option key={status} value={status}>{proposalStatusLabels[status]} ({counts?.[status] ?? 0})</option>
                ))}
                <option value="closed">Κλειστές ({total - openCount})</option>
              </select>
            </label>
            <label>
              Πλατφόρμα
              <select value={filter.platform} onChange={(event) => setFilter({ ...filter, platform: event.target.value as ProposalFilter["platform"] })}>
                <option value="">Όλες</option>
                {PLATFORMS.map((platform) => <option key={platform} value={platform}>{platformLabel(platform)}</option>)}
              </select>
            </label>
          </div>
          <p className="proposal-muted">Πρώτα οι ανοιχτές: για συζήτηση, εγκρίθηκαν ή στάλθηκαν.</p>
          {rows.length === 0 && !loading ? (
            <p className="proposal-muted">{total ? "Καμία πρόταση με αυτά τα φίλτρα." : "Δεν υπάρχουν ακόμα προτάσεις."}</p>
          ) : null}
          {rows.map((row) => (
            <button key={row.code} className={`proposal-row${selected?.code === row.code ? " active" : ""}`}
              aria-current={selected?.code === row.code ? "true" : undefined} onClick={() => void open(row.code, true)}>
              <span className="proposal-row-head">
                <strong>{row.code}</strong>
                <span className={`proposal-badge status-${row.status}`}>{proposalStatusLabels[row.status]}</span>
              </span>
              <span className="proposal-row-title">{row.title}</span>
              <small>
                {platformLabel(row.platform)} · {executorLabels[row.executor]} · {formatDay(row.created_on)}
                {row.notes_count ? ` · ${plural(row.notes_count, "σχόλιο", "σχόλια")}` : ""}
              </small>
            </button>
          ))}
        </aside>
        <article className="proposal-detail panel" ref={detail}>
          {selected ? (
            <>
              <header className="proposal-detail-head">
                <div>
                  <p className="proposal-code">{selected.code}</p>
                  <h2>{selected.title}</h2>
                </div>
                <span className={`proposal-badge status-${selected.status}`}>{proposalStatusLabels[selected.status]}</span>
              </header>
              <dl className="proposal-facts">
                <div><dt>Πλατφόρμα</dt><dd>{platformLabel(selected.platform)}</dd></div>
                <div><dt>Ποιος το κάνει</dt><dd>{executorLabels[selected.executor]}</dd></div>
                <div><dt>Ημερομηνία πρότασης</dt><dd>{formatDay(selected.created_on)}</dd></div>
                <div><dt>Έλεγχος σε 7 ημέρες</dt><dd>{formatDay(selected.check_7_on)}</dd></div>
                <div><dt>Έλεγχος σε 14 ημέρες</dt><dd>{formatDay(selected.check_14_on)}</dd></div>
                {selected.advestiq_status ? <div><dt>Σημείωση ADVESTIQ</dt><dd>{selected.advestiq_status}</dd></div> : null}
              </dl>
              {([["Τι αλλάζει", selected.what], ["Γιατί", selected.why], ["Τι περιμένουμε", selected.expected],
                ["Πώς το αναιρούμε αν δεν πάει καλά", selected.rollback]] as const).map(([title, text]) => text ? (
                <section key={title} className="proposal-section">
                  <h3>{title}</h3>
                  <MarkdownView source={text} />
                </section>
              ) : null)}

              <section className="proposal-section proposal-email">
                <h3>Email προς τον συνεργάτη</h3>
                {selected.message_body ? (
                  <>
                    <p className="proposal-email-subject"><span>Θέμα:</span> {selected.message_subject || "—"}</p>
                    <pre className="proposal-email-body">{selected.message_body}</pre>
                    <div className="proposal-actions">
                      <button className="primary-action compact" onClick={() => void copyEmail()}>
                        <Copy size={16} />Αντιγραφή email
                      </button>
                      <a className="secondary-action compact" href={proposalMailto(selected)}>
                        <Mail size={16} />Άνοιγμα στο email
                      </a>
                      <span className="proposal-copied" role="status">
                        {copied === "done" ? <><Check size={16} />Αντιγράφηκε</> : null}
                        {copied === "failed" ? "Δεν έγινε αντιγραφή. Επίλεξε το κείμενο και πάτα Ctrl+C." : null}
                      </span>
                    </div>
                  </>
                ) : <p className="proposal-muted">Δεν υπάρχει έτοιμο email για αυτή την πρόταση.</p>}
              </section>

              <section className="proposal-section proposal-decision">
                <h3>Η απόφασή σου</h3>
                <div className="proposal-status-buttons" role="group" aria-label="Κατάσταση πρότασης">
                  {STATUSES.map((status) => (
                    <button key={status} className={`proposal-status status-${status}${selected.status === status ? " active" : ""}`}
                      aria-pressed={selected.status === status} disabled={busy || selected.status === status}
                      onClick={() => void changeStatus(status)}>
                      {proposalStatusLabels[status]}
                    </button>
                  ))}
                </div>
                <label className="proposal-comment">
                  Σχόλιο
                  <textarea value={comment} maxLength={10000} rows={3} disabled={busy}
                    placeholder="Γράψε τι αποφάσισες και γιατί…" onChange={(event) => setComment(event.target.value)} />
                </label>
                <div className="proposal-actions">
                  <button className="secondary-action compact" disabled={busy || !comment.trim()} onClick={() => void saveComment()}>
                    <MessageSquarePlus size={16} />Αποθήκευση σχολίου
                  </button>
                  <span className="proposal-muted">Αν πατήσεις κατάσταση, το σχόλιο αποθηκεύεται μαζί.</span>
                </div>
              </section>

              <section className="proposal-section">
                <h3>Σχόλια και ιστορικό</h3>
                {selected.notes.length === 0 ? <p className="proposal-muted">Δεν υπάρχουν ακόμα σχόλια.</p> : (
                  <ol className="proposal-notes">
                    {selected.notes.map((note) => (
                      <li key={note.id} className={`proposal-note author-${note.author}`}>
                        <div className="proposal-note-head">
                          <strong>{note.author === "advestiq" ? "ADVESTIQ" : "Ιδιοκτήτης"}</strong>
                          <time dateTime={note.created_at}>{timeFormat.format(new Date(note.created_at))}</time>
                        </div>
                        {note.status ? (
                          <p>Άλλαξε την κατάσταση σε <span className={`proposal-badge status-${note.status}`}>{proposalStatusLabels[note.status]}</span></p>
                        ) : null}
                        {note.text ? (note.author === "advestiq"
                          ? <MarkdownView source={note.text} />
                          : <p className="proposal-note-text">{note.text}</p>) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </>
          ) : <p className="proposal-muted">{loading ? "Φόρτωση…" : "Διάλεξε μια πρόταση."}</p>}
        </article>
      </div>
    </div>
  );
}
