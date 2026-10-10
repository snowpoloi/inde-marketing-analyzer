// Isolated browser QA: serves the production build with empty reports, never production APIs.
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const dist = path.resolve(__dirname, "../dist");
const calls = [];
const defaults = { statuses: [], aging_statuses: [], processed_statuses: [], completed_statuses: [],
  cancelled_statuses: [], group_by: "day", stale_days: 3 };
const totals = { orders: 0, customers: 0, sub_total: 0, shipping: 0, coupon: 0, taxes: 0,
  total_value: 0, average_order_value: 0 };
const stages = { received: totals, processed: totals, completed: totals, cancelled: totals };
const summary = { ...totals, processed: 0, completed: 0, cancelled: 0, open: 0, other_open: 0,
  processed_rate: 0, completion_rate: 0, stage_totals: stages, stale_orders: 0 };

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const json = value => { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(value)); };
  try {
    if (url.pathname === "/__test_calls") return json(calls);
    if (url.pathname.startsWith("/api/")) {
      let body = "";
      for await (const chunk of req) body += chunk;
      calls.push({ path: url.pathname, query: Object.fromEntries(url.searchParams), body: body ? JSON.parse(body) : null });
      const endpoint = url.pathname.slice(5);
      if (endpoint === "orders/analytics" && req.method === "POST") {
        const input = JSON.parse(body);
        return json({ data: { ...input, summary, status_aging: [], stale_orders: [], stale_orders_total: 0,
          periods: input.periods.map(period => ({ ...period, ...summary, status_counts: [], series: [] })) } });
      }
      if (req.method !== "GET") { res.statusCode = 405; return json({ detail: "Fixture rejects writes" }); }
      if (endpoint === "auth/me") return json({ id: "fixture", email: "fixture@example.test", is_admin: true });
      if (endpoint === "orders/analytics/options") return json({ data: { ...defaults, defaults } });
      if (endpoint === "orders/overview") return json({ data: { summary: { orders: 0, paid_orders: 0, partial_orders: 0,
        unpaid_orders: 0, overpaid_orders: 0, products_total: 0, shipping_total: 0, order_total: 0,
        paid_amount: 0, balance_due: 0, product_quantity: 0, suppliers: 0 }, orders: [], supplier_sales: [], supplier_products: [] } });
      if (endpoint === "banks/transactions") return json({ data: { summary: { deposits: 0, expenses: 0, net_cashflow: 0,
        bank_fees: 0, transactions: 0, unmatched_deposits: 0, ignored_duplicates: 0, ignored_duplicate_amount: 0 },
        expense_categories: [], bank_totals: [], deposits: [], transactions: [] } });
      if (endpoint === "suppliers/summary") return json({ data: { suppliers: 0, purchases: 0, freight: 0,
        matched_products: 0, unmatched_products: 0, products_with_cogs: 0 } });
      if (endpoint === "suppliers/gmail") return json({ data: { configured: false, automatic: false, interval_minutes: 15, job: null, rows: [] } });
      if (endpoint === "supplier-catalog/feeds" || endpoint === "sync/runs") return json([]);
      if (endpoint === "supplier-catalog/products") return json({ rows: [], categories: [], total: 0, offset: 0, limit: 50,
        summary: { products: 0, matched: 0, unmatched: 0 } });
      if (endpoint === "supplier-catalog/period-summary") return json({ rows: [], date_from: url.searchParams.get("date_from"), date_to: url.searchParams.get("date_to") });
      if (endpoint === "dashboard/brand-category") return json({ data: { brands: [], categories: [] } });
      if (endpoint === "dashboard/opencart-sales") return json({ data: { daily: [] } });
      return json({ data: { rows: [], categories: [] } });
    }
    const filename = path.resolve(dist, `.${url.pathname === "/" ? "/index.html" : url.pathname}`);
    if (!filename.startsWith(dist + path.sep)) { res.statusCode = 404; return res.end(); }
    let content = await fs.readFile(filename);
    const ext = path.extname(filename);
    res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" }[ext] || "application/octet-stream");
    if (ext === ".html") content = content.toString().replace("<head>", '<head><script>localStorage.setItem("inde_token","date-range-fixture")</script>');
    res.end(content);
  } catch (error) { res.statusCode = 500; json({ detail: error.message }); }
}).listen(Number(process.env.PORT || 5194), "127.0.0.1", () => console.log("Date range QA preview: http://127.0.0.1:5194"));
