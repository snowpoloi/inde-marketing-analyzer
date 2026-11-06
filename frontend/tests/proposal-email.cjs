const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/utils/proposalEmail.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const compiledModule = { exports: {} };
new Function("exports", "module", compiled)(compiledModule.exports, compiledModule);
const { proposalEmailText, proposalMailto } = compiledModule.exports;

const proposal = { message_subject: "Αλλαγή προϋπολογισμού & ώρες", message_body: "Καλησπέρα σας,\nθα ήθελα μια αλλαγή.\n\nΕυχαριστώ" };
assert.equal(proposalEmailText(proposal), "Θέμα: Αλλαγή προϋπολογισμού & ώρες\n\nΚαλησπέρα σας,\nθα ήθελα μια αλλαγή.\n\nΕυχαριστώ");
assert.equal(proposalEmailText({ message_subject: "", message_body: "Μόνο κείμενο" }), "Μόνο κείμενο");
const link = proposalMailto(proposal);
assert.ok(link.startsWith("mailto:?subject="), "no recipient: the owner chooses it");
const params = new URLSearchParams(link.slice("mailto:?".length));
assert.equal(params.get("subject"), proposal.message_subject);
assert.equal(params.get("body"), "Καλησπέρα σας,\r\nθα ήθελα μια αλλαγή.\r\n\r\nΕυχαριστώ");
assert.ok(!link.includes("&body=Καλησπέρα"), "the body is percent-encoded");
console.log("proposal-email cases passed.");
