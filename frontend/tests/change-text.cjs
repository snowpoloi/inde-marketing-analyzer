const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/utils/changeText.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const compiledModule = { exports: {} };
new Function("exports", "module", compiled)(compiledModule.exports, compiledModule);
const { bulkLine, changeTitle, changedValues, platformLabel, toolLabel, formatValue } = compiledModule.exports;
// Intl puts a no-break space (code 160) before the euro sign; compare with plain spaces.
const plain = (text) => text.split(String.fromCharCode(160)).join(" ");

assert.equal(platformLabel("google_ads"), "Google Ads");
assert.equal(platformLabel("unknown_source"), "unknown_source");
assert.equal(changeTitle({ source: "google_ads", title: "UPDATE", resource_type: "CAMPAIGN_BUDGET" }),
  "Αλλαγή · Προϋπολογισμός καμπάνιας");
assert.equal(changeTitle({ source: "google_ads", title: "CREATE", resource_type: "NEW_THING" }), "Δημιουργία · New thing");
assert.equal(changeTitle({ source: "meta_ads", title: "update_ad_set_budget" }), "Αλλαγή προϋπολογισμού συνόλου διαφημίσεων");
assert.equal(changeTitle({ source: "meta_ads", title: "some_new_event" }), "Some new event");
assert.equal(changeTitle({ source: "shoply", title: "Νέο feed" }), "Νέο feed");
assert.equal(toolLabel("GOOGLE_ADS_EDITOR"), "από το Google Ads Editor");
assert.equal(toolLabel("SOMETHING_ELSE"), null);

// Budget in micros becomes euros; unchanged fields are left out; camelCase field masks are understood.
const budget = changedValues({
  source: "google_ads", title: "UPDATE", detail: "amountMicros,name",
  payload: { old_resource: { campaign_budget: { amount_micros: "40000000", name: "Β" } },
             new_resource: { campaign_budget: { amount_micros: "32500000", name: "Β" } } }
});
assert.deepEqual(budget.map((row) => ({ ...row, before: plain(row.before), after: plain(row.after) })),
  [{ field: "Ποσό προϋπολογισμού", before: "40,00 €", after: "32,50 €" }]);
const status = changedValues({
  source: "google_ads", title: "UPDATE", detail: "status",
  payload: { old_resource: { campaign: { status: "ENABLED" } }, new_resource: { campaign: { status: "PAUSED" } } }
});
assert.deepEqual(status, [{ field: "Κατάσταση", before: "Ενεργή", after: "Σε παύση" }]);
assert.deepEqual(changedValues({ source: "meta_ads", title: "update_ad_set_budget", detail: "x", payload: {} }), []);
assert.deepEqual(changedValues({ source: "google_ads", title: "UPDATE", detail: "status", payload: {} }), []);
assert.equal(formatValue("final_urls", ["https://example.com/a", "https://example.com/b"]),
  "https://example.com/a, https://example.com/b");
assert.equal(formatValue("status", null), "—");

assert.equal(plain(bulkLine({ count: 6582, source: "google_ads", title: "CREATE", actor: "feed@example.com" }, "04:39", "04:53")),
  "6.582 μαζικές δημιουργίες από feed@example.com, 04:39–04:53");
assert.equal(bulkLine({ count: 60, source: "meta_ads", title: "ad_review_approved", actor: null }, "10:00", "10:00"),
  "60 μαζικές αλλαγές «Η διαφήμιση εγκρίθηκε από το Meta» χωρίς όνομα χρήστη, 10:00");

// CSV for Excel: byte-order mark, ";" between columns, quotes doubled, formulas kept as text.
const { changesCsv } = compiledModule.exports;
const csv = changesCsv([{ day: "2026-11-05", occurred_at: "2026-11-05T09:15:00+00:00", source: "google_ads", title: "UPDATE",
  resource_type: "CAMPAIGN_BUDGET", actor: "=HYPERLINK(1)", campaign: "Καμπάνια \"Α\"", detail: "amount_micros",
  client_type: "GOOGLE_ADS_EDITOR" }], () => "11:15");
assert.equal(csv.charCodeAt(0), 0xfeff);
const [head, line] = csv.slice(1).split("\r\n");
assert.equal(head.split(";").length, 8);
assert.equal(line, ['"2026-11-05"', '"11:15"', '"Google Ads"', `"'=HYPERLINK(1)"`, '"Αλλαγή · Προϋπολογισμός καμπάνιας"',
  '"Καμπάνια ""Α"""', '"amount_micros"', '"από το Google Ads Editor"'].join(";"));
console.log("change-text cases passed, including the CSV export.");
