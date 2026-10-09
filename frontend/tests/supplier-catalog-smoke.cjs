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
      let synced = false, saved = false, catalogQuery = null, periodQuery = null;
      let pakoworldFeed = null, pakoworldSynced = false;
      const feed = { id: "f1", code: "MEGAPAP", name: "MEGAPAP", adapter: "megapap", configured: true,
        is_enabled: true, refresh_hours: 24, status: "success", error: null,
        last_synced_at: "2026-10-07T10:00:00Z", counts: { products: 56, matched: 40, unmatched: 16 } };
      const product = { id: "p1", supplier: "MEGAPAP", supplier_code: "0268292", supplier_sku: "CH-N5080-GR", ean: "5203266100377",
        name: "Garden chair 56x60x86.5 cm", category: "Garden chairs", image_url: null, quantity: 168,
        wholesale_price_net: 20.97, retail_price_gross: 26, inde_price: 124, inde_price_net: 100, inde_price_basis: "gross",
        sale_quantity: 1, wholesale_price_per_piece_net:20.97, retail_price_per_piece_gross:26,
        aade_cost_net: 70, aade_cost_sale_net:70, aade_cost_date: "2026-01-02", aade_mark: "MARK-1", gross_profit_per_unit: 30, gross_profit_per_sale:30, gross_margin_percent: 30,
        margin_status: "available", opencart_sku: "CH-N5080-GR", match_method: "exact_identifiers", last_seen_at: feed.last_synced_at };
      await page.route((url) => url.pathname.startsWith("/api/"), async route => {
        const url = new URL(route.request().url()); let response;
        if (url.pathname.endsWith("/auth/me")) response = { is_admin: true };
        else if (url.pathname === "/api/supplier-catalog/feeds" || url.pathname === "/api/supplier-catalog/feeds/f1") {
          if (route.request().method() === "POST") {
            const body = route.request().postDataJSON();
            assert.equal(body.adapter, "pakoworld"); assert.equal(body.code, "AADE_800749270");
            assert.equal(body.name, "Pakketo AE"); assert(body.url.includes("fixture-private-token"));
            pakoworldFeed = { ...feed, id: "f2", code: body.code, name: body.name, adapter: body.adapter, status: "idle" };
            response = pakoworldFeed;
          } else if (route.request().method() === "PUT") {
            const body = route.request().postDataJSON(); assert(!("url" in body)); assert.equal(body.refresh_hours, 48); saved = true;
            response = { ...feed, refresh_hours: 48 };
          } else response = [feed, ...(pakoworldFeed ? [pakoworldFeed] : [])];
        } else if (url.pathname.endsWith("/sync")) {
          synced = true; pakoworldSynced ||= url.pathname.includes("/f2/"); response = { ...(pakoworldSynced ? pakoworldFeed : feed), status: "queued" };
        }
        else if (url.pathname === "/api/supplier-catalog/products") {
          catalogQuery = url.searchParams;
          const offset = Number(url.searchParams.get("offset") || 0), searched = Boolean(url.searchParams.get("q"));
          response = { rows: [product], total: searched ? 1 : 56, offset, limit: 50, categories: ["Garden chairs"], summary: { products: 56, matched: 40, unmatched: 16 } };
        } else if (url.pathname === "/api/supplier-catalog/period-summary") {
          periodQuery = url.searchParams;
          response = {rows:[{feed_id:"f1",supplier:"MEGAPAP",vat_number:"123456789",invoices:1,credit_notes:0,
            purchases_net:140,credits_net:0,net_purchases:140,costed_products_net:140,priced_units:2,costed_units:2,
            average_profit_per_unit:20,average_margin_percent:25,excluded_conflicts:0}]};
        } else if (url.pathname === "/api/supplier-catalog/pricing-settings") response = { sale_vat_rate:24, volumetric_divisor:5000, automatic_costs:true, piece_supplier_ids:[] };
        else if (url.pathname === "/api/supplier-catalog/products/p1") response = { id: "p1", name: product.name, is_current: true,
          packages:[{label:"BOX A",width_cm:"40",length_cm:"100",height_cm:"10",volume_m3:0.04,volumetric_kg:8},
                    {label:"BOX B",width_cm:"50",length_cm:"90",height_cm:"12",volume_m3:0.054,volumetric_kg:10.8}],
          volumetric_divisor:5000, volume_total_m3:0.094, volumetric_total_kg:18.8, details: {
          description: "<b>Garden chair</b><br>Polypropylene", availability: "In stock", volume_item: "0.06502222", weight_item: "13.00444444",
          profile:"MEGAPAP", shop_model:"CH-N5080-GR", shop_sku:"CH-N5080-GR", source_categories:["Garden chairs"],
          inde_category_ids:["456"], category_mapping_status:"mapped",
          packages_per_item: "2", comb_width_cm: "0", comb_height_cm: "0", comb_length_cm: "0", filters: [{ group: "Material", value: "Polypropylene PP" }] } };
        else if (url.pathname === "/api/suppliers/identities") response = {data:{rows:[{ id: "s2", code: "AADE_800749270", name: "Pakketo AE", vat_number: "800749270" }]}};
        else if (url.pathname.endsWith("/settings/integrations") || url.pathname.endsWith("/settings/opencart/order-statuses")) response = [];
        else throw new Error(`Unexpected endpoint: ${url.pathname}`);
        await route.fulfill({ json: response });
      });
      await page.goto("http://127.0.0.1:5187/#supplier-catalog");
      await page.getByRole("heading", { name: "Supplier catalog", exact: true }).waitFor();
      await page.getByText(product.name, { exact: true }).waitFor();
      await page.getByRole("button", { name: "Sort by INDE price (VAT incl.)", exact: true }).waitFor();
      await page.getByRole("button", { name: "Sort by AADE cost / sale (net)", exact: true }).waitFor();
      await page.getByRole("heading", {name:"Supplier purchases & margins",exact:true}).waitFor();
      await page.getByRole("cell", {name:"25%",exact:true}).waitFor();
      await page.getByLabel("Only with gross margin").check();
      await page.getByRole("button", {name:"Sort by Gross margin %",exact:true}).click();
      await page.getByRole("columnheader", {name:"Sort by Gross margin %",exact:true}).waitFor();
      assert.equal(catalogQuery.get("has_margin"), "true");
      assert.equal(catalogQuery.get("sort_by"), "gross_margin_percent");
      assert.equal(catalogQuery.get("sort_direction"), "asc");
      await page.getByRole("button", {name:"Sort by Gross margin %",exact:true}).click();
      await page.getByRole("columnheader", {name:"Sort by Gross margin %",exact:true}).waitFor();
      assert.equal(catalogQuery.get("sort_direction"), "desc");
      await page.getByLabel("Period from").fill("2026-09-01");
      await page.getByLabel("Period to").fill("2026-09-30");
      await page.getByRole("cell", {name:"25%",exact:true}).waitFor();
      assert.equal(periodQuery.get("date_from"), "2026-09-01");
      assert.equal(periodQuery.get("date_to"), "2026-09-30");
      assert.equal(await page.getByRole("cell", { name: "30%", exact: true }).count(), 1);
      assert.equal(await page.getByRole("cell", { name: /70,00/ }).count(), 1);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Page overflows");
      await page.screenshot({ path: `test-results/supplier-catalog-${viewport.width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Details 0268292" }).click();
      await page.getByRole("dialog").getByText("Polypropylene PP", { exact: true }).waitFor();
      await page.getByRole("dialog").getByText("Profile INDE model", {exact:true}).waitFor();
      await page.getByRole("dialog").getByText("456", {exact:true}).waitFor();
      assert.equal(await page.getByRole("cell", {name:"BOX A",exact:true}).count(),1);
      assert.equal(await page.getByRole("cell", {name:"BOX B",exact:true}).count(),1);
      await page.getByRole("columnheader", {name:"Volumetric (kg) / 5000",exact:true}).waitFor();
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
      const formats = await page.getByLabel("XML format", {exact:true}).locator("option").evaluateAll(nodes => nodes.map(node => node.value));
      assert.deepEqual(formats, ["megapap", "pakoworld", "anthemidis", "arlight", "buyway", "daisat", "getters", "gloria", "kanellopoulos", "printezis", "mastershop", "spm"]);
      await page.getByLabel("Supplier feed", { exact: true }).selectOption("f1");
      assert.equal(await page.getByLabel("Private XML URL").inputValue(), "");
      await page.getByLabel("Refresh interval (hours)").fill("48");
      await page.getByRole("button", { name: "Save XML", exact: true }).click();
      await page.getByText("Supplier XML saved.", { exact: true }).waitFor();
      assert(saved);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Settings overflows");
      await page.screenshot({ path: `test-results/supplier-feed-settings-${viewport.width}.png`, fullPage: true });
      await page.getByRole("button", { name: "Add supplier feed", exact: true }).click();
      await page.getByLabel("XML format", { exact: true }).selectOption("gloria");
      assert.equal(await page.getByText("Supplier name", {exact:true}).locator("..").locator("input").inputValue(), "Gloria");
      await page.screenshot({path: `test-results/supplier-multi-feed-${viewport.width}.png`, fullPage:true});
      await page.getByLabel("XML format", { exact: true }).selectOption("pakoworld");
      await page.getByLabel("Registered supplier / AFM", { exact: true }).selectOption("AADE_800749270");
      await page.getByLabel("Private XML URL").fill("https://www.pakoworld.com/?route=feed&token=fixture-private-token");
      await page.getByRole("button", { name: "Save XML", exact: true }).click();
      await page.getByText("Supplier XML saved.", { exact: true }).waitFor();
      assert(pakoworldFeed);
      assert.equal(await page.getByLabel("XML format", { exact: true }).inputValue(), "pakoworld");
      assert.equal(await page.getByLabel("Private XML URL").inputValue(), "");
      await page.getByRole("button", { name: "Sync XML", exact: true }).click();
      await page.getByText("Supplier sync queued.", { exact: true }).waitFor();
      assert(pakoworldSynced);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Pakoworld settings overflows");
      await page.screenshot({ path: `test-results/pakoworld-feed-settings-${viewport.width}.png`, fullPage: true });
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); }
  console.log("Supplier catalog desktop/mobile smoke checks passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
