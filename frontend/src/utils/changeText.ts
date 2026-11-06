// Plain-Greek descriptions of the changes stored from the ad platforms. Standalone (no imports) so the node tests
// can load it directly.

export type ChangeLike = {
  source: string;
  title: string;
  detail?: string | null;
  resource_type?: string | null;
  payload?: Record<string, unknown> | null;
};

const platforms: Record<string, string> = {
  google_ads: "Google Ads",
  meta_ads: "Meta (Facebook, Instagram)",
  tiktok_ads: "TikTok",
  merchant_center: "Merchant Center",
  tracking: "Μετρήσεις (GA4, GTM)",
  shoply: "Shoply",
  catalog: "Κατάλογος προϊόντων",
  business: "Επιχείρηση",
  site: "Site inde.gr",
  other: "Άλλο"
};

export function platformLabel(source: string) {
  return platforms[source] ?? source;
}

const operations: Record<string, [string, string]> = {
  CREATE: ["Δημιουργία", "δημιουργίες"],
  UPDATE: ["Αλλαγή", "αλλαγές"],
  REMOVE: ["Αφαίρεση", "αφαιρέσεις"]
};

// Google Ads change-event resource types.
const resources: Record<string, string> = {
  AD: "Διαφήμιση",
  AD_GROUP: "Ομάδα διαφημίσεων",
  AD_GROUP_AD: "Διαφήμιση ομάδας",
  AD_GROUP_ASSET: "Στοιχείο ομάδας",
  AD_GROUP_BID_MODIFIER: "Προσαρμογή προσφοράς",
  AD_GROUP_CRITERION: "Λέξη-κλειδί ή κοινό ομάδας",
  AD_GROUP_FEED: "Λίστα στοιχείων ομάδας",
  ASSET: "Στοιχείο (κείμενο, εικόνα ή βίντεο)",
  ASSET_GROUP: "Ομάδα στοιχείων (Performance Max)",
  ASSET_GROUP_ASSET: "Στοιχείο ομάδας στοιχείων",
  ASSET_SET: "Σύνολο στοιχείων",
  ASSET_SET_ASSET: "Στοιχείο συνόλου",
  CAMPAIGN: "Καμπάνια",
  CAMPAIGN_ASSET: "Στοιχείο καμπάνιας",
  CAMPAIGN_ASSET_SET: "Σύνολο στοιχείων καμπάνιας",
  CAMPAIGN_BUDGET: "Προϋπολογισμός καμπάνιας",
  CAMPAIGN_CRITERION: "Στόχευση καμπάνιας (περιοχή, γλώσσα, αρνητική λέξη)",
  CAMPAIGN_FEED: "Λίστα στοιχείων καμπάνιας",
  CUSTOMER_ASSET: "Στοιχείο λογαριασμού",
  FEED: "Λίστα στοιχείων (feed)",
  FEED_ITEM: "Γραμμή λίστας στοιχείων"
};

// Google Ads: the tool the change was made with.
const tools: Record<string, string> = {
  GOOGLE_ADS_WEB_CLIENT: "από τη σελίδα του Google Ads",
  GOOGLE_ADS_EDITOR: "από το Google Ads Editor",
  GOOGLE_ADS_MOBILE_APP: "από την εφαρμογή κινητού",
  GOOGLE_ADS_API: "από άλλο πρόγραμμα, μέσω API",
  GOOGLE_ADS_BULK_UPLOAD: "με μαζικό ανέβασμα αρχείου",
  GOOGLE_ADS_SCRIPTS: "από αυτόματο script",
  GOOGLE_ADS_AUTOMATED_RULE: "από αυτόματο κανόνα",
  GOOGLE_ADS_RECOMMENDATIONS: "από τις προτάσεις της Google",
  GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION: "από αυτόματη εφαρμογή προτάσεων της Google",
  SEARCH_ADS_360_SYNC: "από το Search Ads 360",
  SEARCH_ADS_360_POST: "από το Search Ads 360",
  INTERNAL_TOOL: "από εργαλείο της Google",
  OTHER: "από άλλο εργαλείο"
};

// Meta activity log event types. Others are shown with their own words.
const metaEvents: Record<string, string> = {
  create_campaign_group: "Νέα καμπάνια",
  create_campaign_legacy: "Νέα καμπάνια",
  update_campaign_name: "Αλλαγή ονόματος καμπάνιας",
  update_campaign_run_status: "Ενεργοποίηση ή παύση καμπάνιας",
  update_campaign_budget: "Αλλαγή προϋπολογισμού καμπάνιας",
  update_campaign_group_spend_cap: "Αλλαγή ορίου δαπάνης καμπάνιας",
  update_campaign_duration: "Αλλαγή διάρκειας καμπάνιας",
  campaign_ended: "Η καμπάνια τελείωσε",
  create_ad_set: "Νέο σύνολο διαφημίσεων",
  update_ad_set_name: "Αλλαγή ονόματος συνόλου διαφημίσεων",
  update_ad_set_run_status: "Ενεργοποίηση ή παύση συνόλου διαφημίσεων",
  update_ad_set_budget: "Αλλαγή προϋπολογισμού συνόλου διαφημίσεων",
  update_ad_set_bidding: "Αλλαγή προσφοράς συνόλου διαφημίσεων",
  update_ad_set_bid_strategy: "Αλλαγή στρατηγικής προσφορών",
  update_ad_set_target_spec: "Αλλαγή στόχευσης (κοινό)",
  update_ad_set_optimization_goal: "Αλλαγή στόχου βελτιστοποίησης",
  update_ad_set_duration: "Αλλαγή διάρκειας συνόλου διαφημίσεων",
  create_ad: "Νέα διαφήμιση",
  update_ad_creative: "Αλλαγή δημιουργικού διαφήμισης",
  edit_and_update_ad_creative: "Αλλαγή δημιουργικού διαφήμισης",
  update_ad_run_status: "Ενεργοποίηση ή παύση διαφήμισης",
  update_ad_friendly_name: "Αλλαγή ονόματος διαφήμισης",
  ad_review_approved: "Η διαφήμιση εγκρίθηκε από το Meta",
  ad_review_declined: "Η διαφήμιση απορρίφθηκε από το Meta",
  first_delivery_event: "Η διαφήμιση άρχισε να προβάλλεται",
  create_audience: "Νέο κοινό",
  update_audience: "Αλλαγή κοινού",
  delete_audience: "Διαγραφή κοινού",
  add_images: "Νέες εικόνες",
  ad_account_update_spend_limit: "Αλλαγή ορίου δαπάνης λογαριασμού",
  ad_account_billing_charge: "Χρέωση λογαριασμού",
  account_spending_limit_reached: "Ο λογαριασμός έφτασε το όριο δαπάνης",
  campaign_spending_limit_reached: "Η καμπάνια έφτασε το όριο δαπάνης"
};

// Google Ads fields that change most often.
const fields: Record<string, string> = {
  amount_micros: "Ποσό προϋπολογισμού",
  total_amount_micros: "Συνολικός προϋπολογισμός",
  status: "Κατάσταση",
  name: "Όνομα",
  target_roas: "Στόχος απόδοσης διαφήμισης (τζίρος ανά 1 €)",
  target_cpa_micros: "Στόχος κόστους ανά πώληση",
  cpc_bid_micros: "Μέγιστη προσφορά ανά κλικ",
  final_urls: "Σελίδα προορισμού",
  start_date: "Ημερομηνία έναρξης",
  end_date: "Ημερομηνία λήξης",
  bidding_strategy_type: "Στρατηγική προσφορών"
};

const values: Record<string, string> = {
  ENABLED: "Ενεργή",
  PAUSED: "Σε παύση",
  REMOVED: "Αφαιρέθηκε"
};

function humanize(value: string) {
  const words = value.replace(/[_.]+/g, " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : value;
}

export function operationLabel(title: string, plural = false) {
  const known = operations[title.toUpperCase()];
  return known ? known[plural ? 1 : 0] : title;
}

export function resourceLabel(type?: string | null) {
  return type ? resources[type] ?? humanize(type) : null;
}

export function toolLabel(clientType?: string | null) {
  return clientType ? tools[clientType] ?? null : null;
}

// What changed, in one short line.
export function changeTitle(change: ChangeLike) {
  if (change.source === "google_ads" && operations[change.title.toUpperCase()]) {
    const resource = resourceLabel(change.resource_type);
    return resource ? `${operationLabel(change.title)} · ${resource}` : operationLabel(change.title);
  }
  if (change.source === "meta_ads") return metaEvents[change.title] ?? humanize(change.title);
  return change.title;
}

const euro = new Intl.NumberFormat("el-GR", { style: "currency", currency: "EUR" });

function snake(segment: string) {
  return segment.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

function lookup(resource: unknown, path: string[]): unknown {
  let value: unknown = resource;
  for (const segment of path) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const record = value as Record<string, unknown>;
    value = segment in record ? record[segment] : record[snake(segment)];
  }
  return value;
}

function inner(resource: unknown) {
  // Google wraps the resource in its type: {"campaign_budget": {...}}.
  if (!resource || typeof resource !== "object") return undefined;
  const entries = Object.values(resource as Record<string, unknown>);
  return entries.length === 1 ? entries[0] : resource;
}

export function formatValue(field: string, value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (field.endsWith("_micros") && !Number.isNaN(Number(value))) return euro.format(Number(value) / 1_000_000);
  if (typeof value === "boolean") return value ? "ναι" : "όχι";
  if (Array.isArray(value)) return value.map((item) => formatValue(field, item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value).slice(0, 160);
  const text = String(value);
  return values[text] ?? text;
}

// Google Ads: before and after for each changed field, when the stored change event carries them.
export function changedValues(change: ChangeLike) {
  if (change.source !== "google_ads" || !change.detail || !change.payload) return [];
  const before = inner(change.payload.old_resource);
  const after = inner(change.payload.new_resource);
  if (!before && !after) return [];
  return change.detail.split(/[,\s]+/).filter(Boolean).slice(0, 8).map((path) => {
    const segments = path.split(".");
    const last = snake(segments[segments.length - 1]);
    return {
      field: fields[last] ?? humanize(last),
      before: formatValue(last, lookup(before, segments)),
      after: formatValue(last, lookup(after, segments))
    };
  }).filter((row) => row.before !== row.after);
}

// "6.582 μαζικές δημιουργίες από χρήστη Χ, 04:39–04:53"
export function bulkLine(group: { count: number; source: string; title: string; actor: string | null },
                         from: string, to: string) {
  const count = new Intl.NumberFormat("el-GR").format(group.count);
  const who = group.actor ? `από ${group.actor}` : "χωρίς όνομα χρήστη";
  const when = from === to ? from : `${from}–${to}`;
  const what = group.source === "google_ads" && operations[group.title.toUpperCase()]
    ? operationLabel(group.title, true)
    : `αλλαγές «${changeTitle(group)}»`;
  return `${count} μαζικές ${what} ${who}, ${when}`;
}

// Excel in Greek uses ";" between columns. Cells that start like a formula are kept as text.
function csvCell(value: string) {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

type CsvChange = ChangeLike & {
  day: string; occurred_at: string; actor: string | null; campaign: string | null; client_type: string | null;
};

// The individual changes as a CSV file for Excel: UTF-8 with a byte-order mark, so Greek shows correctly.
export function changesCsv(rows: CsvChange[], time: (value: string) => string) {
  const header = ["Ημερομηνία", "Ώρα", "Πλατφόρμα", "Ποιος", "Τι άλλαξε", "Καμπάνια", "Λεπτομέρειες", "Πώς"];
  const lines = rows.map((row) => [row.day, time(row.occurred_at), platformLabel(row.source), row.actor ?? "",
    changeTitle(row), row.campaign ?? "", row.detail ?? "", toolLabel(row.client_type) ?? ""]);
  return String.fromCharCode(0xfeff) + [header, ...lines].map((cells) => cells.map(csvCell).join(";")).join("\r\n");
}
