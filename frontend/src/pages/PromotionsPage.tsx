import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Clapperboard, Copy, Download, ExternalLink, Film, Loader2, Play, Plus, RefreshCw, Search, Upload, X } from "lucide-react";
import { api } from "../api/client";
import type { PromotionAsset, PromotionCampaign, PromotionCampaignSummary, PromotionFormat, PromotionInput, PromotionProduct, PromotionReview } from "../api/promotions";
import { DateRangeControls, useReportPeriod } from "../components/DateRangeControls";
import "../styles/promotions.css";

const money = (n:number) => new Intl.NumberFormat("el-GR",{style:"currency",currency:"EUR"}).format(n);
const formats: PromotionFormat[] = ["9:16","16:9","1:1"];
const channels = {"9:16":"TikTok · Reels · Shorts","16:9":"YouTube · Google Ads","1:1":"Meta Feed"};
const status:Record<string,string> = {draft:"Προσχέδιο", needs_review:"Για έλεγχο", approved:"Εγκεκριμένο"};
const emptyReview:PromotionReview = {product_identity:false, cta_and_text:false, image_and_audio_rights:false, platform_format:false};
const reviewLabels:Record<keyof PromotionReview,string> = {product_identity:"Το προϊόν είναι ίδιο με την πραγματική φωτογραφία",
  cta_and_text:"Τα κείμενα και το τελικό inde.gr είναι σωστά",image_and_audio_rights:"Έχω δικαίωμα χρήσης εικόνας και ήχου",platform_format:"Έλεγξα αναλογία, διάρκεια και απαιτήσεις πλατφόρμας"};

function download(blob:Blob, filename:string) {
  const url=URL.createObjectURL(blob), link=document.createElement("a"); link.href=url; link.download=filename; link.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}

export function PromotionsPage() {
  const {range,setRange}=useReportPeriod();
  const [products,setProducts]=useState<PromotionProduct[]>([]);
  const [selected,setSelected]=useState<PromotionProduct[]>([]);
  const [campaigns,setCampaigns]=useState<PromotionCampaignSummary[]>([]);
  const [campaign,setCampaign]=useState<PromotionCampaign|null>(null);
  const [search,setSearch]=useState("");
  const [minimum,setMinimum]=useState(18);
  const [eligible,setEligible]=useState(true);
  const [tab,setTab]=useState<"products"|"campaigns">("products");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [loading,setLoading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [activeFormat,setActiveFormat]=useState<PromotionFormat>("9:16");
  const [form,setForm]=useState<Omit<PromotionInput,"product_ids"|"date_from"|"date_to">>({title:"",style:"cinematic",formats:[...formats],duration:15,
    hook:"Ο χώρος σου, αλλιώς.",cta:"Ανακάλυψέ το στο inde.gr",notes:""});
  const [media,setMedia]=useState<{id:string;url:string}|null>(null);
  const [review,setReview]=useState<PromotionReview>({...emptyReview});
  const [uploadFormat,setUploadFormat]=useState<PromotionFormat>("9:16");
  const [mediaError,setMediaError]=useState(false);
  const requestSequence=useRef(0);
  const historySequence=useRef(0);
  const uploadInput=useRef<HTMLInputElement>(null);
  useEffect(()=>()=>{requestSequence.current++;historySequence.current++;},[]);
  useEffect(()=>()=>{if(media) URL.revokeObjectURL(media.url);},[media]);

  async function loadProducts() {
    const sequence=++requestSequence.current; setLoading(true);setError("");
    try {const result=await api.promotionProducts(range.from,range.to,search,minimum,eligible);
      if(sequence===requestSequence.current) setProducts(result.rows);
    } catch(e) {if(sequence===requestSequence.current) setError(String(e));}
    finally {if(sequence===requestSequence.current) setLoading(false);}
  }
  async function loadCampaigns() {
    try {setCampaigns((await api.promotionCampaigns()).rows);} catch(e) {setError(String(e));}
  }
  useEffect(()=>{const timer=window.setTimeout(()=>void loadProducts(),250);return()=>window.clearTimeout(timer);},[range.from,range.to,minimum,eligible]);
  useEffect(()=>{void loadCampaigns();},[]);

  async function action(callback:()=>Promise<void>) {
    setBusy(true);setError("");setNotice("");
    try {await callback();} catch(e) {setError(String(e));} finally {setBusy(false);}
  }
  function toggle(product:PromotionProduct) {
    setSelected(previous=>previous.some(p=>p.id===product.id)?previous.filter(p=>p.id!==product.id):previous.length<3?[...previous,product]:previous);
  }
  function showCampaign(next:PromotionCampaign) {
    setCampaign(next);setActiveFormat(next.brief.parameters.formats[0]);setUploadFormat(next.brief.parameters.formats[0]);
    setMedia(null);setReview({...emptyReview});setMediaError(false);
  }
  async function openCampaign(id:string) {
    const sequence=++historySequence.current;
    await action(async()=>{const result=await api.promotionCampaign(id);if(sequence===historySequence.current) showCampaign(result);});
  }
  async function create() {
    await action(async()=>{
      const result=await api.promotionCreate({...form,title:form.title||`INDE · ${selected[0]?.name||"Προϊόντα"}`.slice(0,180),
        date_from:range.from,date_to:range.to,product_ids:selected.map(p=>p.id)});
      showCampaign(result);await loadCampaigns();setNotice("Το πλάνο αποθηκεύτηκε. Δεν έγινε δημιουργία ή χρέωση βίντεο.");
    });
  }
  async function preview(asset:PromotionAsset) {
    await action(async()=>{const blob=await api.promotionMedia(asset.id);setMedia({id:asset.id,url:URL.createObjectURL(blob)});
      setReview({...emptyReview});setMediaError(false);});
  }
  async function copy(value:string) {
    try {await navigator.clipboard.writeText(value);setNotice("Αντιγράφηκε.");} catch {setError("Η αντιγραφή δεν επιτράπηκε από τον browser.");}
  }
  const variant=campaign?.brief.variants.find(v=>v.aspect_ratio===activeFormat);
  const currentAsset=campaign?.assets.find(a=>a.id===media?.id);

  return <div className="page-stack promotions-page">
    <header className="page-header"><div><h1>Προώθηση</h1><span className="promotion-provider"><Clapperboard size={15}/>Higgsfield · Συνδρομή</span></div>
      <div className="promotion-header-actions"><DateRangeControls range={campaign?{from:campaign.brief.parameters.date_from,to:campaign.brief.parameters.date_to}:range} onChange={setRange} disabled={loading||busy||Boolean(campaign)}/>
        <a className="secondary-action" href="https://higgsfield.ai/" target="_blank" rel="noreferrer"><ExternalLink size={16}/>Higgsfield</a></div>
    </header>
    {error?<div className="error" role="alert">{error}</div>:null}
    {notice?<div className="notice" role="status">{notice}</div>:null}
    {!campaign?<>
      <nav className="promotion-tabs" aria-label="Προώθηση"><button aria-selected={tab==="products"} onClick={()=>setTab("products")}>Προϊόντα</button>
        <button aria-selected={tab==="campaigns"} onClick={()=>{setTab("campaigns");void loadCampaigns();}}>Καμπάνιες <span>{campaigns.length}</span></button></nav>
      {tab==="campaigns"?<section aria-label="Καμπάνιες" className="promotion-history">
        {campaigns.length?campaigns.map(row=><button key={row.id} disabled={busy} className="promotion-history-row" onClick={()=>void openCampaign(row.id)}>
          <Film size={20}/><strong>{row.title}</strong><span>{new Date(row.created_at).toLocaleDateString("el-GR")}</span><span className="promotion-badge">{status[row.status]||row.status}</span></button>):<p className="promotion-empty">Δεν υπάρχουν αποθηκευμένες καμπάνιες.</p>}
      </section>:<div className="promotion-workspace">
        <section className="promotion-picker" aria-label="Επιλογή προϊόντων">
          <form className="promotion-filters" onSubmit={event=>{event.preventDefault();void loadProducts();}}>
            <label>Προϊόν / SKU<input value={search} maxLength={150} onChange={e=>setSearch(e.target.value)}/></label>
            <label>Ελάχιστο περιθώριο %<input type="number" min="0" max="100" step="1" value={minimum} onChange={e=>setMinimum(Number(e.target.value))}/></label>
            <button className="icon-button" type="submit" disabled={loading} aria-label="Αναζήτηση προϊόντων" title="Αναζήτηση προϊόντων">{loading?<Loader2 size={17} className="promotion-spin"/>:<Search size={17}/>}</button>
            <label className="promotion-check"><input type="checkbox" checked={eligible} onChange={e=>setEligible(e.target.checked)}/>Διαθέσιμα με γνωστό περιθώριο</label>
          </form>
          <div className="promotion-section-heading"><h2>Προτεινόμενα προϊόντα</h2><span>{products.length} προϊόντα</span></div>
          {loading?<div className="promotion-empty" role="status">Φόρτωση προϊόντων...</div>:!products.length?<div className="promotion-empty">Δεν βρέθηκαν προϊόντα με τα επιλεγμένα κριτήρια.</div>:<div className="promotion-product-grid">
            {products.map(product=>{const checked=selected.some(p=>p.id===product.id);return <article key={product.id} className={`promotion-product ${checked?"selected":""}`}>
              <div className="promotion-product-image">{product.image_url?<img src={product.image_url} alt={product.name} loading="lazy" referrerPolicy="no-referrer"/>:<Film size={32}/>}
                <button className="icon-button" aria-label={`${checked?"Αφαίρεση":"Επιλογή"} ${product.sku}`} title={checked?"Αφαίρεση προϊόντος":"Επιλογή προϊόντος"}
                  disabled={(!checked&&selected.length>=3)||!product.stock||!product.image_url||!product.link} aria-pressed={checked} onClick={()=>toggle(product)}>{checked?<Check size={18}/>:<Plus size={18}/>}</button></div>
              <div className="promotion-product-copy"><span>{product.sku} · {product.brand||"INDE"}</span><h3>{product.name}</h3>
                <strong>{money(product.price_gross)} <small>με ΦΠΑ</small></strong>
                <div className="promotion-product-metrics"><span>{product.orders} παραγγελίες</span><span>{product.stock} απόθεμα</span>
                  <span>{product.margin_percent===null?"Κόστος σε εκκρεμότητα":`${product.margin_percent.toLocaleString("el-GR",{maximumFractionDigits:1})}% περιθώριο`}</span></div>
                {product.reasons.length?<p className="promotion-warning">{product.reasons.join(" · ")}</p>:null}
                {product.link?<a href={product.link} target="_blank" rel="noreferrer">Προϊόν INDE <ExternalLink size={12}/></a>:null}
              </div></article>;})}
          </div>}
        </section>
        <aside className="promotion-composer" aria-label="Νέο πλάνο">
          <div className="promotion-section-heading"><h2>Νέο πλάνο</h2><span>{selected.length}/3 προϊόντα</span></div>
          <div className="promotion-selection">{selected.length?selected.map(p=><div key={p.id}>{p.image_url?<img src={p.image_url} alt=""/>:null}<span>{p.sku}</span>
            <button className="icon-button" aria-label={`Αφαίρεση επιλεγμένου ${p.sku}`} title="Αφαίρεση" onClick={()=>toggle(p)}><X size={14}/></button></div>):<p>Κανένα επιλεγμένο προϊόν</p>}</div>
          <label>Όνομα καμπάνιας<input maxLength={180} value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label>
          <label>Κατεύθυνση<select value={form.style} onChange={e=>setForm({...form,style:e.target.value as PromotionInput["style"]})}>
            <option value="cinematic">Cinematic product film</option><option value="editorial">Design editorial</option><option value="detail">Detail reveal</option></select></label>
          <label>Διάρκεια<select value={form.duration} onChange={e=>setForm({...form,duration:Number(e.target.value) as 15|30})}><option value={15}>15 δευτερόλεπτα</option><option value={30}>30 δευτερόλεπτα</option></select></label>
          <fieldset className="promotion-formats"><legend>Εκδόσεις</legend>{formats.map(ratio=><label key={ratio}><input type="checkbox" checked={form.formats.includes(ratio)} onChange={e=>setForm({...form,formats:e.target.checked?[...form.formats,ratio]:form.formats.filter(r=>r!==ratio)})}/>
            <span><strong>{ratio}</strong><small>{channels[ratio]}</small></span></label>)}</fieldset>
          <label>Αρχικό μήνυμα<input maxLength={100} value={form.hook} onChange={e=>setForm({...form,hook:e.target.value})}/></label>
          <label>Τελικό κάλεσμα<input maxLength={100} value={form.cta} onChange={e=>setForm({...form,cta:e.target.value})}/></label>
          <label>Σκηνοθετικές σημειώσεις<textarea rows={3} maxLength={2000} value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
          <button className="primary-action" disabled={busy||!selected.length||!form.formats.length||!form.hook.trim()||!form.cta.trim()} onClick={()=>void create()}>
            {busy?<Loader2 size={17} className="promotion-spin"/>:<Clapperboard size={17}/>}Αποθήκευση πλάνου</button>
        </aside>
      </div>}
    </>:<>
      <div className="promotion-campaign-header"><button className="secondary-action" disabled={busy} onClick={()=>{historySequence.current++;setCampaign(null);setTab("campaigns");setMedia(null);setNotice("");void loadCampaigns();}}><ArrowLeft size={16}/>Καμπάνιες</button>
        <h2>{campaign.title}</h2><span className="promotion-badge">{status[campaign.status]||campaign.status}</span>
        <button className="secondary-action" disabled={busy} onClick={()=>void action(async()=>{download(await api.promotionPackage(campaign.id),`inde-promotion-${campaign.id}.zip`);})}><Download size={16}/>Πακέτο Higgsfield</button>
        <button className="icon-button" title="Ανανέωση καμπάνιας" aria-label="Ανανέωση καμπάνιας" disabled={busy} onClick={()=>void openCampaign(campaign.id)}><RefreshCw size={16}/></button>
      </div>
      <section className="promotion-storyboard" aria-label="Storyboard">{campaign.brief.storyboard.map(scene=><div key={scene.label}><span>{scene.time}</span><h3>{scene.label}</h3><p>{scene.copy}</p></div>)}</section>
      <div className="promotion-campaign-workspace">
        <section className="promotion-direction" aria-label="Πλάνα Higgsfield">
          <div className="promotion-format-tabs" role="tablist" aria-label="Αναλογίες βίντεο">{campaign.brief.variants.map(v=><button key={v.aspect_ratio} role="tab" aria-selected={activeFormat===v.aspect_ratio} onClick={()=>setActiveFormat(v.aspect_ratio)}>{v.aspect_ratio}<small>{v.channels.join(" · ")}</small></button>)}</div>
          {variant?<><div className="promotion-shot-list">{variant.shots.map((shot,index)=>{const p=campaign.brief.products.find(p=>p.sku===shot.sku);return <article key={shot.sku} className="promotion-shot">
            <img src={shot.image_url} alt={p?.name||shot.sku}/><div><span>Πλάνο {index+1} · {shot.seconds}s</span><h3>{p?.name}</h3>
              <details><summary>Σκηνοθετικό prompt</summary><textarea aria-label={`Prompt ${shot.sku}`} readOnly value={shot.prompt}/></details>
              <button className="secondary-action" onClick={()=>void copy(shot.prompt)}><Copy size={14}/>Αντιγραφή prompt</button>
              <a href={shot.image_url} target="_blank" rel="noreferrer" className="secondary-action"><ExternalLink size={14}/>Πραγματική φωτογραφία</a>
            </div></article>;})}</div>
            <div className={`promotion-end-card ratio-${activeFormat.replace(":","-")}`}><strong>INDE</strong><p>{campaign.brief.parameters.cta}</p><span>inde.gr</span></div>
          </>:null}
          <div className="promotion-links"><h2>Σύνδεσμοι διαφήμισης</h2>{Object.entries(campaign.brief.ad_links).map(([channel,url])=><div key={channel}><label>{channel}<input readOnly value={url} aria-label={`Σύνδεσμος ${channel}`}/></label>
            <button className="icon-button" title={`Αντιγραφή ${channel}`} aria-label={`Αντιγραφή συνδέσμου ${channel}`} onClick={()=>void copy(url)}><Copy size={16}/></button></div>)}</div>
        </section>
        <aside className="promotion-assets" aria-label="Τελικά βίντεο">
          <div className="promotion-section-heading"><h2>Τελικά βίντεο</h2><span>{campaign.assets.length}</span></div>
          <div className="promotion-upload"><select aria-label="Αναλογία εισαγωγής" value={uploadFormat} disabled={busy} onChange={e=>setUploadFormat(e.target.value as PromotionFormat)}>
            {campaign.brief.parameters.formats.map(r=><option key={r} value={r}>{r}</option>)}</select>
            <input ref={uploadInput} type="file" accept="video/mp4,.mp4" hidden onChange={e=>{const file=e.target.files?.[0];if(file){if(file.size>64*1024*1024){setError("Μέγιστο μέγεθος MP4: 64 MB.");}
              else void action(async()=>{showCampaign(await api.promotionUpload(campaign.id,uploadFormat,file));setNotice("Το βίντεο αποθηκεύτηκε και περιμένει έλεγχο.");});}e.target.value="";}}/>
            <button className="secondary-action" disabled={busy} onClick={()=>uploadInput.current?.click()}><Upload size={16}/>Εισαγωγή MP4</button></div>
          {!campaign.assets.length?<div className="promotion-empty">Δεν έχει εισαχθεί τελικό βίντεο.</div>:campaign.assets.map(asset=><div className="promotion-asset-row" key={asset.id}>
            <span><strong>{asset.aspect_ratio}</strong><small>{status[asset.status]||asset.status}</small></span>
            <button className="icon-button" title="Προεπισκόπηση βίντεο" aria-label={`Προεπισκόπηση ${asset.aspect_ratio}`} disabled={busy} onClick={()=>void preview(asset)}><Play size={16}/></button>
            <button className="icon-button" title="Λήψη MP4" aria-label={`Λήψη ${asset.aspect_ratio}`} disabled={busy} onClick={()=>void action(async()=>{download(await api.promotionMedia(asset.id),`inde-${asset.aspect_ratio.replace(":","x")}.mp4`);})}><Download size={16}/></button>
          </div>)}
          {media&&currentAsset?<div className="promotion-review"><video key={media.url} src={media.url} controls preload="metadata" onError={()=>setMediaError(true)} aria-label="Προεπισκόπηση τελικού βίντεο"/>
            {mediaError?<p className="promotion-warning">Το αρχείο δεν αναπαράγεται στον browser. Δεν μπορεί να εγκριθεί.</p>:null}
            {currentAsset.status==="approved"?<span className="promotion-badge">Εγκεκριμένο</span>:<><h3>Έλεγχος πριν τη χρήση</h3>
              {(Object.keys(reviewLabels) as Array<keyof PromotionReview>).map(key=><label className="promotion-check" key={key}><input type="checkbox" checked={review[key]} onChange={e=>setReview({...review,[key]:e.target.checked})}/>{reviewLabels[key]}</label>)}
              <button className="primary-action" disabled={busy||mediaError||!Object.values(review).every(Boolean)} onClick={()=>void action(async()=>{setCampaign(await api.promotionApprove(currentAsset.id,review));setNotice("Το βίντεο εγκρίθηκε. Δεν έγινε δημοσίευση διαφήμισης.");await loadCampaigns();})}><Check size={17}/>Έγκριση βίντεο</button>
            </>}
          </div>:null}
        </aside>
      </div>
    </>}
  </div>;
}
