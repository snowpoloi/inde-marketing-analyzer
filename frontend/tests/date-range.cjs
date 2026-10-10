const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/utils/dateRange.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const compiledModule = { exports: {} };
new Function("exports", "module", compiled)(compiledModule.exports, compiledModule);
const { presetRange, localIso, datePresets } = compiledModule.exports;

assert.deepEqual(datePresets.map(item => item.key), ["today", "yesterday", "last-7", "this-month", "previous-month"]);
let checks = 0;
function range(preset, now, from, to) {
  const date = new Date(now);
  const before = date.getTime();
  assert.deepEqual(presetRange(preset, date), { from, to, preset });
  assert.equal(date.getTime(), before, "Must not mutate the reference date");
  checks++;
}

range("today", "2026-10-11T00:05:00", "2026-10-11", "2026-10-11");
range("yesterday", "2026-10-11T23:55:00", "2026-10-10", "2026-10-10");
range("last-7", "2026-10-11T12:00:00", "2026-10-05", "2026-10-11");
range("this-month", "2026-10-11T00:05:00", "2026-10-01", "2026-10-11");
range("previous-month", "2026-10-11T12:00:00", "2026-09-01", "2026-09-30");
range("this-month", "2026-10-01T00:05:00", "2026-10-01", "2026-10-01");
range("previous-month", "2026-01-01T00:05:00", "2025-12-01", "2025-12-31");
range("yesterday", "2026-01-01T00:05:00", "2025-12-31", "2025-12-31");
range("last-7", "2026-01-03T00:05:00", "2025-12-28", "2026-01-03");
range("previous-month", "2024-03-31T12:00:00", "2024-02-01", "2024-02-29");
range("previous-month", "2025-03-31T12:00:00", "2025-02-01", "2025-02-28");
range("last-7", "2026-03-31T12:00:00", "2026-03-25", "2026-03-31");
range("last-7", "2026-10-28T12:00:00", "2026-10-22", "2026-10-28");
assert.equal(localIso(new Date("2026-10-11T00:05:00")), "2026-10-11");
console.log(`${checks} date-range cases passed, including leap years, year boundaries, DST and local midnight.`);
