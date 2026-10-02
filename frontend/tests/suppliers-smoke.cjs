// Run against a local Vite server. All API traffic is isolated fixture data.
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  await mkdir("test-results", { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "chrome" });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const context = await browser.newContext({ viewport });
      await context.addInitScript(() => localStorage.setItem("inde_token", "isolated-fixture"));
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      let matched = false;
      let manualSaved = false;
      let threshold = null;
      const mapping = { mapping_id: "m1", supplier_id: "s1", supplier: "MEGAPAP", supplier_sku: "GP041-0025,4",
        supplier_code: "0212605", supplier_ean: null, product_catalog_id: "p1", opencart_product_id: "1",
        opencart_sku: "INDE-1", opencart_model: "GP041-0025,4", product_name: "Supplier product example",
        current_cogs: 8.73, previous_cogs: 8.5, cost_change_percent: 2.71, cost_source: "invoice",
        cost_reference: "MEGAPAP | invoice INV3", cost_date: "2026-10-02", cost_confidence: 1,
        match_status: "matched", match_method: "verified", match_confidence: 1, verified: true, conversion_factor: 1 };
      await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
        const url = new URL(route.request().url());
        let response;
        if (url.pathname.endsWith("/auth/me")) response = { id: "u1", email: "fixture@example.com", is_admin: true };
        else if (url.pathname.endsWith("/suppliers/summary")) response = { data: { suppliers: 1, purchases: 85.68, freight: 4.9, matched_products: 1, unmatched_products: matched ? 0 : 1, products_with_cogs: 1 } };
        else if (url.pathname.endsWith("/suppliers/products")) response = { data: { rows: [mapping] } };
        else if (url.pathname.endsWith("/suppliers/unmatched")) response = { data: { rows: matched ? [] : [{ mapping_id: "m2", supplier: "MEGAPAP", supplier_sku: "OTHER", supplier_code: "123", supplier_ean: null, description: "Unresolved product", status: "unmatched", candidates: [] }] } };
        else if (url.pathname.endsWith("/suppliers/performance")) response = { data: { rows: [{ supplier_id: "s1", supplier: "MEGAPAP", purchases: 85.68, freight: 4.9, freight_ratio: 5.72, orders: 1,
          average_order: 85.68, average_freight_per_order: 4.9, free_shipping_orders: 0, paid_shipping_orders: 1, unknown_shipping_orders: 0,
          free_shipping_threshold: threshold, threshold_gap: threshold ? 14.32 : 0, potential_freight_savings: 0, price_increases: 1,
          shipping_trend: [{ month: "2026-10", freight: 4.9 }], shipping_by_type: [{ shipping_type: "INBOUND", freight: 4.9 }],
          margin_erosion_products: [{ mapping_id: "m1", product_name: mapping.product_name, supplier_sku: mapping.supplier_sku, previous_cogs: 8.5, current_cogs: 8.73, increase_percent: 2.71 }] }] } };
        else if (url.pathname.endsWith("/catalog-search")) response = { data: { rows: [{ product_catalog_id: "p1", product_id: "1", sku: "INDE-1", model: "GP041-0025,4", name: mapping.product_name, method: "manual_search", confidence: 0 }] } };
        else if (url.pathname.endsWith("/verify")) { matched = true; response = { data: { mapping_id: "m2", verified: true, costs_created: 1 } }; }
        else if (url.pathname.endsWith("/cost-history")) response = { data: { rows: [
          { id: "c1", date: "2026-10-02", source: "invoice", reference: "INV3", net_unit_cost: 8.73, quantity: 1, confidence: 1, currency: "EUR", status: "active" },
          ...(manualSaved ? [{ id: "c2", date: "2026-10-03", source: "manual", reference: "manual-source", net_unit_cost: 9, quantity: 1, confidence: 1, currency: "EUR", status: "active" }] : [])] } };
        else if (url.pathname.endsWith("/costs/manual")) { manualSaved = true; response = { data: { cost_id: "c2", duplicate: false } }; }
        else if (url.pathname.endsWith("/settings")) { threshold = route.request().postDataJSON().free_shipping_threshold; response = { data: { saved: true } }; }
        else if (url.pathname.endsWith("/shipping-simulation")) response = { data: { threshold: 100, eligible_orders: 0, orders: 1, potential_savings: 0, additional_purchase_to_threshold: 14.32 } };
        else if (url.pathname.endsWith("/imports/json")) response = { data: { batch_id: "b1", duplicate: false, documents_imported: 1, matched_lines: 1, unmatched_lines: 0 } };
        else throw new Error(`Unmocked request: ${url.pathname}`);
        await route.fulfill({ json: response });
      });
      await page.goto(`${process.env.SUPPLIER_PREVIEW_URL || "http://127.0.0.1:5175"}/#suppliers`);
      await page.getByRole("heading", { name: "Suppliers & COGS" }).waitFor();
      await page.getByText(mapping.product_name, { exact: true }).waitFor();
      await page.screenshot({ path: `test-results/suppliers-${viewport.width}.png`, fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Page overflow");
      await page.getByRole("button", { name: `Cost history ${mapping.product_name}` }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText("INV3", { exact: true }).waitFor();
      await dialog.getByLabel("Net cost / sales unit").fill("9");
      await dialog.getByLabel("Source reference").fill("manual-source");
      await dialog.getByRole("button", { name: "Save cost" }).click();
      await dialog.getByText("manual-source", { exact: true }).waitFor();
      await dialog.getByTitle("Close history").click();
      await page.getByRole("button", { name: "Unmatched products", exact: true }).click();
      assert(await page.getByRole("button", { name: "Verify", exact: true }).isDisabled());
      await page.getByLabel("Search catalog OTHER").fill("GP041");
      await page.getByTitle("Search catalog", { exact: true }).click();
      await page.getByLabel("Select product OTHER").selectOption("p1");
      await page.getByRole("button", { name: "Verify", exact: true }).click();
      await page.getByText("No unresolved products found.").waitFor();
      await page.getByRole("button", { name: "Supplier performance", exact: true }).click();
      await page.locator("summary").click();
      await page.getByLabel("Free-shipping threshold").fill("100");
      await page.getByRole("button", { name: "Simulate", exact: true }).click();
      await page.getByText(/Eligible orders: 0 \/ 1/).waitFor();
      assert.equal(threshold, null, "Simulation must not change saved settings");
      await page.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByText(/Gap to threshold: 14,32/).waitFor();
      assert.equal(threshold, 100);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `test-results/supplier-performance-${viewport.width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Import", exact: true }).click();
      await page.locator('input[type="file"]').setInputFiles({ name: "example.json", mimeType: "application/json", buffer: Buffer.from("{}") });
      await page.getByRole("button", { name: "Import", exact: true }).last().click();
      await page.getByText("1 documents imported, 1 matched and 0 sent to review.").waitFor();
      assert.equal(await page.locator('input[type="file"]').inputValue(), "");
      assert.deepEqual(errors, []);
      await context.close();
      console.log(`Supplier workflows passed at ${viewport.width}px`);
    }
  } finally { await browser.close(); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
