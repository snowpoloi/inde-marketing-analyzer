const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  await mkdir("test-results", { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const context = await browser.newContext({ viewport });
      await context.addInitScript(() => localStorage.setItem("inde_token", "isolated-fixture"));
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      let synced = false, saved = false;
      const feed = { id: "f1", code: "MEGAPAP", name: "MEGAPAP", adapter: "megapap", configured: true,
        is_enabled: true, refresh_hours: 24, status: "success", error: null,
        last_synced_at: "2026-10-07T10:00:00Z", counts: { products: 56, matched: 40, unmatched: 16 } };
      const product = { id: "p1", supplier: "MEGAPAP", supplier_code: "0268292", supplier_sku: "CH-N5080-GR", ean: "5203266100377",
        name: "Garden chair 56x60x86.5 cm", category: "Garden chairs", image_url: null, quantity: 168,
        wholesale_price_net: 20.97, retail_price_gross: 26, inde_price: 124, inde_price_net: 100, inde_price_basis: "gross",
        aade_cost_net: 70, aade_cost_date: "2026-01-02", aade_mark: "MARK-1", gross_profit_per_unit: 30, gross_margin_percent: 30,
        margin_status: "available", opencart_sku: "CH-N5080-GR", match_method: "exact_identifiers", last_seen_at: feed.last_synced_at };
      await page.route((url) => url.pathname.startsWith("/api/"), async route => {
        const url = new URL(route.request().url()); let response;
        if (url.pathname.endsWith("/auth/me")) response = { is_admin: true };
        else if (url.pathname === "/api/supplier-catalog/feeds" || url.pathname === "/api/supplier-catalog/feeds/f1") {
          if (route.request().method() === "PUT") {
            const body = route.request().postDataJSON(); assert(!("url" in body)); assert.equal(body.refresh_hours, 48); saved = true;
            response = { ...feed, refresh_hours: 48 };
          } else response = [feed];
        } else if (url.pathname.endsWith("/sync")) { synced = true; response = { ...feed, status: "queued" }; }
        else if (url.pathname === "/api/supplier-catalog/products") {
          const offset = Number(url.searchParams.get("offset") || 0), searched = Boolean(url.searchParams.get("q"));
          response = { rows: [product], total: searched ? 1 : 56, offset, limit: 50, categories: ["Garden chairs"], summary: { products: 56, matched: 40, unmatched: 16 } };
        } else if (url.pathname === "/api/supplier-catalog/products/p1") response = { id: "p1", name: product.name, is_current: true, details: {
          description: "<b>Garden chair</b><br>Polypropylene", availability: "In stock", volume_item: "0.06502222", weight_item: "13.00444444",
          packages_per_item: "1", comb_width_cm: "0", comb_height_cm: "0", comb_length_cm: "0", filters: [{ group: "Material", value: "Polypropylene PP" }] } };
        else if (url.pathname.endsWith("/settings/integrations") || url.pathname.endsWith("/settings/opencart/order-statuses")) response = [];
        else throw new Error(`Unexpected endpoint: ${url.pathname}`);
        await route.fulfill({ json: response });
      });
      await page.goto("http://127.0.0.1:5187/#supplier-catalog");
      await page.getByRole("heading", { name: "Supplier catalog", exact: true }).waitFor();
      await page.getByText(product.name, { exact: true }).waitFor();
      await page.getByRole("columnheader", { name: "INDE price", exact: true }).waitFor();
      await page.getByRole("columnheader", { name: "AADE cost / unit (net)", exact: true }).waitFor();
      assert.equal(await page.getByRole("cell", { name: "30%", exact: true }).count(), 1);
      assert.equal(await page.getByRole("cell", { name: /70,00/ }).count(), 1);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Page overflows");
      await page.screenshot({ path: `test-results/supplier-catalog-${viewport.width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Details 0268292" }).click();
      await page.getByRole("dialog").getByText("Polypropylene PP", { exact: true }).waitFor();
      await page.screenshot({ path: `test-results/supplier-catalog-detail-${viewport.width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Close product" }).click();
      await page.getByRole("button", { name: "Next page", exact: true }).click();
      await page.getByText("51-56 / 56", { exact: true }).waitFor();
      await page.getByLabel("Search", { exact: true }).fill("0268292");
      await page.getByText("1-1 / 1", { exact: true }).waitFor();
      await page.getByLabel("Supplier", { exact: true }).selectOption("f1");
      await page.getByRole("button", { name: "Sync XML", exact: true }).click();
      assert(synced);
      await page.getByRole("button", { name: "Settings", exact: true }).click();
      await page.getByRole("heading", { name: "Supplier XML feeds" }).waitFor();
      await page.getByLabel("Supplier feed", { exact: true }).selectOption("f1");
      assert.equal(await page.getByLabel("Private XML URL").inputValue(), "");
      await page.getByLabel("Refresh interval (hours)").fill("48");
      await page.getByRole("button", { name: "Save XML", exact: true }).click();
      await page.getByText("Supplier XML saved.", { exact: true }).waitFor();
      assert(saved);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Settings overflows");
      await page.screenshot({ path: `test-results/supplier-feed-settings-${viewport.width}.png`, fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
  console.log("Supplier catalog desktop/mobile smoke checks passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
