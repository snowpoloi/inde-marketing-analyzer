const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/utils/changePeriods.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const compiledModule = { exports: {} };
new Function("exports", "module", compiled)(compiledModule.exports, compiledModule);
const { changePeriodRange, changePeriods, athensToday, windowDays, MAX_CHANGE_DAYS } = compiledModule.exports;

assert.deepEqual(changePeriods.map((item) => item.key),
  ["today", "yesterday", "last-7", "last-30", "this-week", "this-month", "previous-month"]);
let checks = 0;
function range(period, now, from, to) {
  assert.deepEqual(changePeriodRange(period, new Date(now)), { from, to }, `${period} at ${now}`);
  checks++;
}

// Friday 6/11/2026, midday in Athens (UTC+2 in winter).
range("today", "2026-11-06T10:00:00Z", "2026-11-06", "2026-11-06");
range("yesterday", "2026-11-06T10:00:00Z", "2026-11-05", "2026-11-05");
range("last-7", "2026-11-06T10:00:00Z", "2026-10-31", "2026-11-06");
range("last-30", "2026-11-06T10:00:00Z", "2026-10-08", "2026-11-06");
range("this-week", "2026-11-06T10:00:00Z", "2026-11-02", "2026-11-06");
range("this-month", "2026-11-06T10:00:00Z", "2026-11-01", "2026-11-06");
range("previous-month", "2026-11-06T10:00:00Z", "2026-10-01", "2026-10-31");
// 00:30 in Athens is still the previous day in UTC: Athens decides.
range("today", "2026-11-05T22:30:00Z", "2026-11-06", "2026-11-06");
range("yesterday", "2026-11-05T22:30:00Z", "2026-11-05", "2026-11-05");
// Summer time (UTC+3): Sunday 25/10/2026 at 00:30 Athens; the week started on Monday 19/10.
range("today", "2026-10-24T21:30:00Z", "2026-10-25", "2026-10-25");
range("this-week", "2026-10-24T21:30:00Z", "2026-10-19", "2026-10-25");
// Monday: the week is that day only.
range("this-week", "2026-11-02T08:00:00Z", "2026-11-02", "2026-11-02");
// Year and month ends, leap years.
range("yesterday", "2026-01-01T08:00:00Z", "2025-12-31", "2025-12-31");
range("this-week", "2026-01-01T08:00:00Z", "2025-12-29", "2026-01-01");
range("previous-month", "2026-01-15T08:00:00Z", "2025-12-01", "2025-12-31");
range("previous-month", "2026-03-31T08:00:00Z", "2026-02-01", "2026-02-28");
range("previous-month", "2028-03-31T08:00:00Z", "2028-02-01", "2028-02-29");
range("last-30", "2026-03-01T08:00:00Z", "2026-01-31", "2026-03-01");
assert.equal(athensToday(new Date("2026-12-31T22:30:00Z")), "2027-01-01");
assert.equal(windowDays("2026-11-06", "2026-11-06"), 1);
assert.equal(windowDays("2026-08-05", "2026-11-05"), MAX_CHANGE_DAYS);
assert.equal(windowDays("2026-10-01", "2026-10-31"), 31);
console.log(`${checks} change-period cases passed, in Athens time across midnight, summer time and year ends.`);
