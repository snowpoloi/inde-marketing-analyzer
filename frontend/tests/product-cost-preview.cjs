// Local-only UI fixtures; no supplier, Gmail or fiscal API calls.
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const dist = path.resolve(__dirname, "../dist");
const base = { product_id: "1", sku: "QA-CHAIR", model: "QA-1", name: "Chair / invoice after customer order",
  brand: "QA Supplier", category: "Chairs", quantity: 2, orders: 2, revenue: 200, net_sales: 200,
  cogs: 120, gross_profit: 80, margin_percent: 40, cost_coverage_percent: 100, current_unit_cogs: null,
  cogs_source: "aade_invoice", cogs_date: "2026-10-02", cogs_confidence: 1, cost_basis: "estimated",
  cost_methods: ["later_invoice_estimate"], cost_issues: [], average_unit_price: 100, average_quantity_per_order: 1,
  catalog_status: "Available", catalog_quantity: 10, image_url: null, link: null,
  cost_provenance: [{ source: "aade_invoice", reference: "AADE MARK QA-1", invoice_number: "A / 123",
    date: "2026-10-02", unit_cost: 60, confidence: 1, cost_methods: ["later_invoice_estimate"], order_ids: ["QA-100", "QA-101"] }] };
const rows = [base,
  { ...base, product_id: "2", sku: "QA-OLD", name: "Chair / historical price", cogs_date: "2026-08-01",
    cost_methods: ["historical_estimate"], cost_provenance: [] },
  { ...base, product_id: "3", sku: "QA-CONFLICT", name: "Chair / conflicting prices", cogs: null,
    gross_profit: null, margin_percent: null, cost_coverage_percent: 0, cogs_source: null,
    cogs_confidence: null, cogs_date: null, cost_methods: [], cost_issues: ["conflicting_invoice_prices"], cost_provenance: [] },
  { ...base, product_id: "4", sku: "QA-PARTIAL", name: "Chair / partial coverage", cogs: null,
    gross_profit: null, margin_percent: null, cost_coverage_percent: 50, cost_issues: ["no_eligible_cost"] }];

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const json = value => { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(value)); };
  try {
    if (url.pathname.startsWith("/api/")) {
      if (req.method !== "GET") { res.statusCode = 405; return json({ detail: "Fixture rejects writes" }); }
      if (url.pathname === "/api/auth/me") return json({ id: "fixture", email: "fixture@example.test", is_admin: true });
      return json({ data: { rows } });
    }
    const filename = path.resolve(dist, `.${url.pathname === "/" ? "/index.html" : url.pathname}`);
    if (!filename.startsWith(dist + path.sep)) { res.statusCode = 404; return res.end(); }
    let content = await fs.readFile(filename);
    const ext = path.extname(filename);
    res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[ext] || "application/octet-stream");
    if (ext === ".html") content = content.toString().replace("<head>", '<head><script>localStorage.setItem("inde_token","product-cost-fixture")</script>');
    res.end(content);
  } catch (error) { res.statusCode = 500; json({ detail: error.message }); }
}).listen(5195, "127.0.0.1", () => console.log("Products cost QA: http://127.0.0.1:5195/#products"));
