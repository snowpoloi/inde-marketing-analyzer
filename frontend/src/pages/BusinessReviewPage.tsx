import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight, ChevronLeft, ChevronRight, Download, Pause, Plus, RefreshCw, Save, Upload } from "lucide-react";
import { api } from "../api/client";
import type { BusinessReview, ReviewEvidence, ReviewJobs, ReviewParameters, ReviewRow } from "../api/businessReview";
import { DateRangeControls, useReportPeriod } from "../components/DateRangeControls";
import { DataTable, type Column } from "../components/DataTable";
import { localIso, type DateRange } from "../utils/dateRange";
import "../styles/business-review.css";

const number = new Intl.NumberFormat("el-GR", { maximumFractionDigits: 2 });
const money = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });
const sources = ["google_ads","meta_ads","tiktok_ads","ga4","merchant_center","search_console","opencart","aade"];
const metrics: Array<[string,string,boolean]> = [
  ["order_value","Order value (incl. tax / shipping)",true], ["orders","Counted orders",false],
  ["ad_spend","Ad spend",true], ["blended_ratio","Order value / ad spend",false],
  ["average_order","Average order",true], ["ad_cost_per_order","Ad spend / order",true],
  ["ga4_value","GA4 purchase value",true], ["ga4_purchases","GA4 purchases",false],
  ["aade_income_net","AADE income less credits (net)",true], ["aade_expense_net","AADE expenses less credits (net)",true],
  ["bank_credits","Bank credits (cash inflows)",true], ["bank_debits","Bank debits (cash outflows)",true],
  ["merchant_clicks","Merchant clicks",false], ["organic_clicks","Search Console clicks (stored rows)",false],
];
const format = (v: number | null | undefined, currency = false) => v == null ? "-" : (currency ? money : number).format(v);
const labels: Record<string,string> = {value:"Value",cost:"Spend",conversions:"Conversions",roas:"ROAS",
  clicks:"Clicks",impressions:"Impressions",quantity:"Quantity",orders:"Orders",unit_price:"Average unit price",sessions:"Sessions",
  purchases:"Purchases",credits:"Credits",debits:"Debits",transactions:"Transactions"};

function previousMonth(range: DateRange): DateRange {
  const shift = (value: string) => {
    const [year, month, day] = value.split("-").map(Number);
    return localIso(new Date(year, month - 2, Math.min(day, new Date(year, month - 1, 0).getDate())));
  };
  return {from:shift(range.from), to:shift(range.to)};
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = document.createElement("a"); link.href=url; link.download=name; link.click();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
}

export function BusinessReviewPage() {
  const {range,setRange} = useReportPeriod();
  const [baseline,setBaseline] = useState(()=>previousMonth(range));
  const [withCosts,setWithCosts] = useState(false);
  const [report,setReport] = useState<BusinessReview|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [message,setMessage] = useState("");
  const [view,setView] = useState("overview");
  const [dimension,setDimension] = useState("campaigns");
  const [metric,setMetric] = useState("value");
  const [search,setSearch] = useState("");
  const [ascending,setAscending] = useState(false);
  const [page,setPage] = useState(0);
  const [jobs,setJobs] = useState<ReviewJobs>({counts:{},rows:[]});
  const [historyFrom,setHistoryFrom] = useState("2025-12-01");
  const [historyTo,setHistoryTo] = useState(localIso(new Date()));
  const [providers,setProviders] = useState(sources);
  const [saved,setSaved] = useState<Array<{id:string;title:string;created_at:string}>>([]);
  const [snapshot,setSnapshot] = useState("");
  const [evidence,setEvidence] = useState<ReviewEvidence>({
    source:"shoply",occurred_at:`${localIso(new Date())}T12:00`,title:"",detail:"",actor:"",
    reference_url:"",evidence_type:"manual",
  });
  const sequence = useRef(0);
  const params: ReviewParameters = {date_from:range.from,date_to:range.to,
    baseline_from:baseline.from,baseline_to:baseline.to,with_costs:withCosts};
  async function compare() {
    const id=++sequence.current;
    setBusy(true); setError(""); setSnapshot("");
    try { const result=await api.businessReview(params); if(id===sequence.current) setReport(result); }
    catch(e) { if(id===sequence.current) setError(String(e)); }
    finally { if(id===sequence.current) setBusy(false); }
  }
  async function action(run:()=>Promise<unknown>, success: string) {
    setBusy(true);setError("");setMessage("");
    try { await run(); setMessage(success); }
    catch(e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function loadJobs() { setJobs(await api.reviewJobs()); }
  useEffect(()=>{void compare(); void api.reviewReports().then(r=>setSaved(r.rows)).catch(e=>setError(String(e)));
    return ()=>{sequence.current++;};},[]);
  // Only the job list polls, and only while its tab is open. Reports never auto-refresh.
  useEffect(()=>{
    if(view!=="history") return;
    let active=true;
    const load=()=>api.reviewJobs().then(r=>{if(active)setJobs(r);}).catch(e=>{if(active)setError(String(e));});
    void load();
    const timer=setInterval(()=>{if(!document.hidden) void load();},15000);
    return ()=>{active=false;clearInterval(timer);};
  },[view]);
  useEffect(()=>{setPage(0);},[dimension,metric,search,ascending,report]);
  const rows = useMemo(()=>{
    const filtered=(report?.comparisons[dimension]||[]).filter(r=>`${r.name} ${r.key} ${r.sku||""} ${r.source||""}`.toLowerCase().includes(search.toLowerCase()));
    return filtered.sort((a,b)=>{
      const av=a.metrics[metric]?.delta, bv=b.metrics[metric]?.delta;
      if(av==null)return bv==null?0:1;if(bv==null)return -1;
      return ascending? av-bv : bv-av;
    });
  },[report,dimension,metric,search,ascending]);
  const columns: Column<ReviewRow>[] = [
    {key:"name",header:"Name / identity",render:r=><><strong>{r.name}</strong><small>{r.sku||r.key} {r.source}</small></>},
    {key:"baseline",header:"Baseline",align:"right",render:r=>format(r.metrics[metric]?.previous)},
    {key:"current",header:"Current",align:"right",render:r=>format(r.metrics[metric]?.current)},
    {key:"delta",header:"Change",align:"right",sortable:true,sortDirection:ascending?"asc":"desc",
      onSort:()=>setAscending(!ascending),render:r=>format(r.metrics[metric]?.delta)},
    {key:"percent",header:"Change %",align:"right",render:r=>r.metrics[metric]?.percent==null?"-":`${format(r.metrics[metric].percent)}%`},
    {key:"state",header:"Presence",render:r=>r.state.replace(/_/g," ")},
  ];
  const stale = report && !snapshot && (report.current.date_from!==range.from || report.current.date_to!==range.to ||
    report.baseline.date_from!==baseline.from || report.baseline.date_to!==baseline.to ||
    Boolean(report.current.costs)!==withCosts);
  const csvCell=(v:unknown)=>`"${String(v??"").replace(/^[=+@-]/,"'$&").replace(/"/g,'""')}"`;
  return <div className="business-review">
    <div className="page-header"><h1>Business review</h1><div className="review-actions">
      <button className="primary-action" onClick={()=>void compare()} disabled={busy}><RefreshCw size={16}/>Compare</button>
      <button className="secondary-action" disabled={busy||!report||Boolean(stale)||Boolean(snapshot)} onClick={()=>void action(async()=>{
        const r=await api.reviewSave(params);setSaved((await api.reviewReports()).rows);setSnapshot(r.id);
        setReport(await api.reviewReport(r.id));
      },"Snapshot saved.")}><Save size={16}/>Save snapshot</button>
      <button className="secondary-action" disabled={!report} onClick={()=>download("business-review.json",JSON.stringify(report,null,2),"application/json")}><Download size={16}/>Export report</button>
    </div></div>
    <div className="review-periods">
      <div><strong>Current period</strong><DateRangeControls range={range} onChange={setRange} disabled={busy}/></div>
      <button className="review-swap icon-button" title="Swap periods" aria-label="Swap periods" disabled={busy}
        onClick={()=>{setRange(baseline);setBaseline(range);}}><ArrowLeftRight size={18}/></button>
      <div><strong>Baseline period</strong><DateRangeControls label="Baseline period" range={baseline} onChange={setBaseline} disabled={busy}/></div>
      <label><input type="checkbox" checked={withCosts} onChange={e=>setWithCosts(e.target.checked)} disabled={busy}/>Include invoice cost estimates</label>
    </div>
    <div className="review-actions">
      <button className="secondary-action" disabled={busy} onClick={()=>setBaseline(previousMonth(range))}>Same dates previous month</button>
      <label>Saved review<select aria-label="Saved review" disabled={busy} value={snapshot} onChange={e=>{
        const id=e.target.value;setSnapshot(id);if(id)void action(async()=>setReport(await api.reviewReport(id)),"Saved snapshot loaded.");
        else void compare();
      }}><option value="">Live data</option>{saved.map(r=><option key={r.id} value={r.id}>{r.title} · {new Date(r.created_at).toLocaleString("el-GR")}</option>)}</select></label>
    </div>
    {error&&<div className="error" role="alert">{error}</div>}
    {message&&<div className="notice" role="status">{message}</div>}
    {busy&&<div role="status" className="notice">Loading review...</div>}
    {stale&&<div className="notice">Period changed. Displayed data is still for the dates below until Compare completes.</div>}
    {report&&<p className="review-basis">{snapshot?"Saved snapshot":"Data snapshot"}: {report.current.date_from} – {report.current.date_to}
      {" vs "}{report.baseline.date_from} – {report.baseline.date_to} · {new Date(report.generated_at).toLocaleString("el-GR")}</p>}
    <div className="view-tabs" role="tablist" aria-label="Business review views">
      {[["overview","Overview"],["drivers","Changes & drivers"],["timeline","Change history"],["coverage","Data coverage"],["history","Historical imports"]].map(([key,label])=>
        <button role="tab" aria-selected={view===key} className={view===key?"active":""} key={key} onClick={()=>setView(key)}>{label}</button>)}
    </div>
    {view==="overview"&&report&&<>
      <section className="review-section"><h2>Business comparison</h2>
        <DataTable rows={metrics} empty="No metrics" columns={[
          {key:"metric",header:"Metric / basis",render:r=>r[1]},
          {key:"before",header:"Baseline",align:"right",render:r=>format(report.metrics[r[0]].previous,r[2])},
          {key:"after",header:"Current",align:"right",render:r=>format(report.metrics[r[0]].current,r[2])},
          {key:"delta",header:"Change",align:"right",render:r=>format(report.metrics[r[0]].delta,r[2])},
          {key:"pct",header:"Change %",align:"right",render:r=>report.metrics[r[0]].percent==null?"-":`${format(report.metrics[r[0]].percent)}%`},
          {key:"daily",header:"Current / day",align:"right",render:r=>{
            const v=report.metrics[r[0]].current;return ["order_value","orders","ad_spend"].includes(r[0])&&v!=null?format(v/report.current.days,r[2]):"-";
          }},
        ]}/>
      </section>
      <section className="review-section"><h2>Ad platform attribution</h2>
        <DataTable rows={report.sources} empty="No ads loaded" columns={[
          {key:"name",header:"Platform",render:r=>r.name},
          {key:"cost",header:"Spend: baseline / current",align:"right",render:r=>`${format(r.cost.previous,true)} / ${format(r.cost.current,true)}`},
          {key:"value",header:"Attributed value: baseline / current",align:"right",render:r=>`${format(r.value.previous,true)} / ${format(r.value.current,true)}`},
          {key:"roas",header:"ROAS: baseline / current",align:"right",render:r=>`${format(r.roas.previous)} / ${format(r.roas.current)}`},
        ]}/>
      </section>
      {report.current.costs&&<section className="review-section"><h2>Covered product cost estimates</h2>
        <DataTable rows={[{period:"Baseline",...report.baseline.costs!},{period:"Current",...report.current.costs}]} empty="" columns={[
          {key:"period",header:"Period",render:r=>r.period},
          {key:"coverage",header:"Fully costed / products",render:r=>`${r.fully_costed_products} / ${r.products}`},
          {key:"net",header:"Covered net sales",align:"right",render:r=>format(r.covered_net_sales,true)},
          {key:"cogs",header:"Covered COGS",align:"right",render:r=>format(r.covered_cogs,true)},
          {key:"profit",header:"Covered gross profit",align:"right",render:r=>format(r.covered_gross_profit,true)},
        ]}/>
        <p className="review-basis">{report.current.costs.basis}</p>
      </section>}
      <section className="review-section"><h2>Findings</h2>{report.findings.map((f,i)=><div className={`review-finding ${f.severity}`} key={i}>
        <strong>{f.title}</strong><p>{f.detail}</p></div>)}</section>
      <section className="review-section"><h2>Interpretation & limitations</h2><ul>{report.limitations.map(x=><li key={x}>{x}</li>)}</ul></section>
    </>}
    {view==="drivers"&&report&&<section className="review-section">
      <div className="review-actions">
        <label>Dimension<select aria-label="Dimension" value={dimension} onChange={e=>{setDimension(e.target.value);setMetric(
          e.target.value==="banks"?"credits":["merchant_products","organic_pages"].includes(e.target.value)?"clicks":"value");}}>
          {Object.keys(report.comparisons).map(k=><option key={k}>{k}</option>)}</select></label>
        <label>Metric<select aria-label="Metric" value={metric} onChange={e=>setMetric(e.target.value)}>
          {Object.keys(report.comparisons[dimension]?.[0]?.metrics||{value:{}}).map(k=><option key={k} value={k}>{labels[k]||k}</option>)}</select></label>
        <label>Search<input value={search} onChange={e=>setSearch(e.target.value)}/></label>
        <button className="secondary-action" onClick={()=>download(`review-${dimension}.csv`,"\uFEFF"+[
          ["Name","Identity","SKU",`${metric}: ${report.baseline.date_from} / ${report.baseline.date_to}`,
            `${metric}: ${report.current.date_from} / ${report.current.date_to}`,"Delta","Percent"].map(csvCell).join(","),
          ...rows.map(r=>[r.name,r.key,r.sku,r.metrics[metric]?.previous,r.metrics[metric]?.current,
            r.metrics[metric]?.delta,r.metrics[metric]?.percent].map(csvCell).join(","))].join("\r\n"),"text/csv;charset=utf-8")}>
          <Download size={16}/>Export selection</button>
      </div>
      <DataTable columns={columns} rows={rows.slice(page*50,(page+1)*50)} rowKey={r=>r.key} empty="No comparable records for this selection."/>
      <div className="review-pagination"><button className="icon-button" aria-label="Previous page" disabled={page===0} onClick={()=>setPage(page-1)}><ChevronLeft size={16}/></button>
        <span>{rows.length?`${page*50+1}–${Math.min((page+1)*50,rows.length)} / ${rows.length}`:"0"}</span>
        <button className="icon-button" aria-label="Next page" disabled={(page+1)*50>=rows.length} onClick={()=>setPage(page+1)}><ChevronRight size={16}/></button></div>
    </section>}
    {view==="timeline"&&<section className="review-section">
      <h2>Changes in the two selected periods</h2>
      <p className="review-basis">API = recorded provider event. Email / manual / export = reported evidence. Timing alone does not establish causation.</p>
      {report?.events_truncated&&<div className="notice">Showing the latest 500 events. Narrow the periods for older records.</div>}
      <DataTable rows={report?.events||[]} empty="No change evidence stored for these periods." rowKey={r=>r.id||r.title} columns={[
        {key:"date",header:"When / source",render:r=><>{new Date(r.occurred_at).toLocaleString("el-GR")}<small>{r.source} · {r.evidence_type}</small></>},
        {key:"actor",header:"Actor / object",render:r=><>{r.actor||"-"}<small>{r.object_id}</small></>},
        {key:"event",header:"Change / evidence",render:r=><><strong>{r.title}</strong><p>{r.detail}</p>
          {r.reference_url&&<a href={r.reference_url} target="_blank" rel="noreferrer">Open source</a>}
          {r.payload&&Object.keys(r.payload).length>0&&<details><summary>Recorded fields</summary><pre>{JSON.stringify(r.payload,null,2)}</pre></details>}</>},
      ]}/>
      <details className="review-editor"><summary>Add supporting evidence</summary>
        <form onSubmit={e=>{e.preventDefault();void action(async()=>{await api.reviewEvidence(evidence);
          setEvidence({...evidence,title:"",detail:""});setReport(await api.businessReview(params));setSnapshot("");},"Evidence saved.");}}>
          <div className="review-form">
            <label>Source<select value={evidence.source} onChange={e=>setEvidence({...evidence,source:e.target.value})}>
              {["shoply","google_ads","meta_ads","tiktok_ads","merchant_center","tracking","catalog","business"].map(s=><option key={s}>{s}</option>)}</select></label>
            <label>Evidence type<select value={evidence.evidence_type} onChange={e=>setEvidence({...evidence,evidence_type:e.target.value})}>
              {["manual","email","export"].map(s=><option key={s}>{s}</option>)}</select></label>
            <label>Date / time (Athens)<input required type="datetime-local" value={evidence.occurred_at} onChange={e=>setEvidence({...evidence,occurred_at:e.target.value})}/></label>
            <label>Reported by<input value={evidence.actor||""} onChange={e=>setEvidence({...evidence,actor:e.target.value})}/></label>
            <label>Title<input required maxLength={500} value={evidence.title} onChange={e=>setEvidence({...evidence,title:e.target.value})}/></label>
            <label>Source link<input type="url" value={evidence.reference_url||""} onChange={e=>setEvidence({...evidence,reference_url:e.target.value})}/></label>
            <label className="review-wide">Details<textarea rows={4} value={evidence.detail} onChange={e=>setEvidence({...evidence,detail:e.target.value})}/></label>
          </div><button className="primary-action" disabled={busy}><Plus size={16}/>Save evidence</button>
        </form>
      </details>
      <div className="review-actions">
        <button className="secondary-action" onClick={()=>download("change-history-template.csv","source,occurred_at,title,detail,actor,object_id,reference_url,evidence_type\r\n","text/csv")}><Download size={16}/>CSV template</button>
        <label className="review-upload"><Upload size={16}/>Import evidence CSV<input type="file" accept=".csv" disabled={busy} onChange={e=>{
          const file=e.target.files?.[0];if(file)void action(async()=>{await api.reviewImport(file);
            setReport(await api.businessReview(params));setSnapshot("");},"Evidence imported.");e.target.value="";
        }}/></label>
      </div>
    </section>}
    {view==="coverage"&&report&&<section className="review-section"><h2>Acquisition coverage</h2>
      <p className="review-basis">Days with rows are not proof of completeness. Banks require statement reconciliation; current Merchant status is not historical approval history.</p>
      <DataTable rows={[...report.current.coverage.map(r=>({...r,period:"Current"})),...report.baseline.coverage.map(r=>({...r,period:"Baseline"}))]}
        empty="No coverage" columns={[
          {key:"period",header:"Period / source",render:r=><>{r.period}<small>{r.source}</small></>},
          {key:"status",header:"Coverage",render:r=>r.status.replace(/_/g," ")},
          {key:"days",header:"Verified sync days / requested",render:r=>`${r.verified_sync_days} / ${r.days_requested}`},
          {key:"rows",header:"Stored rows / days with activity",render:r=>`${r.rows} / ${r.days_with_rows}`},
          {key:"range",header:"First / last activity",render:r=>`${r.first||"-"} / ${r.last||"-"}`},
        ]}/>
    </section>}
    {view==="history"&&<section className="review-section"><h2>Historical acquisition</h2>
      <div className="review-actions">
        <label>From<input type="date" value={historyFrom} max={historyTo} onChange={e=>setHistoryFrom(e.target.value)}/></label>
        <label>To<input type="date" value={historyTo} min={historyFrom} max={localIso(new Date())} onChange={e=>setHistoryTo(e.target.value)}/></label>
        <button className="primary-action" disabled={busy||!providers.length} onClick={()=>void action(async()=>{
          const r=await api.reviewHistory({date_from:historyFrom,date_to:historyTo,providers});await loadJobs();
          setMessage(`${r.queued} new windows queued.`);
        },"Historical windows queued; progress appears below.")}><Download size={16}/>Queue history</button>
        <button className="secondary-action" disabled={busy} onClick={()=>void action(async()=>{await api.reviewPause();await loadJobs();},"Pending windows paused; the active window will finish.")}><Pause size={16}/>Pause pending</button>
        <button className="secondary-action" disabled={busy} onClick={()=>void action(async()=>{await api.reviewRetry();await loadJobs();},"Failed, skipped and paused windows requeued.")}><RefreshCw size={16}/>Retry / resume</button>
      </div>
      <div className="review-providers">{sources.map(s=><label key={s}><input type="checkbox" checked={providers.includes(s)}
        onChange={e=>setProviders(e.target.checked?[...providers,s]:providers.filter(p=>p!==s))}/>{s}</label>)}</div>
      <p className="review-basis">Google API change history: recent 28 days only; older history needs an export. Shoply changes need its logs/export.
        Banks are imported in Banks. Provider access and campaign settings remain unchanged.</p>
      <p>{Object.entries(jobs.counts).map(([key,count])=>`${key}: ${count}`).join(" · ")||"No historical jobs yet."}</p>
      <DataTable rows={jobs.rows} empty="No queued windows." rowKey={r=>r.id} columns={[
        {key:"source",header:"Provider / kind",render:r=><>{r.provider}<small>{r.kind}</small></>},
        {key:"range",header:"Period",render:r=>`${r.date_from} / ${r.date_to}`},
        {key:"status",header:"Status",render:r=>r.status},
        {key:"count",header:"Records / attempts",render:r=>`${r.records} / ${r.attempts}`},
        {key:"error",header:"Acquisition note",render:r=>r.error||"-"},
      ]}/>
    </section>}
  </div>;
}
