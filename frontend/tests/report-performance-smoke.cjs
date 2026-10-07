const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
      await context.addInitScript(() => localStorage.setItem("inde_token", "isolated-fixture"));
      const page = await context.newPage();
      const errors = [], calls = [];
      page.on("pageerror", error => errors.push(error.message));
      const summary = {income_documents:1,expense_documents:1,cancelled_documents:0,income_gross:124,
        expense_gross:24.8,income_vat:24,expense_vat:4.8,opencart_orders:1,opencart_revenue:124,revenue_gap:0,revenue_gap_percent:0};
      const invoice = {source_endpoint:"RequestDocs",record_type:"full_document",direction:"expense",invoice_type:"1.1",
        document_count:1,mark:"MARK-TEST",uid:null,issue_date:"2026-10-06",issuer_vat:"123456789",issuer_name:"Fixture supplier",
        counterpart_vat:"802216736",series:"TEST",aa:"1",currency:"EUR",net_value:20,vat_amount:4.8,gross_value:24.8,
        is_cancelled:false,cancelled_by_mark:null,identity_key:"test-invoice",opencart_order:null,
        line_items:[{source:"AADE",line_number:"1",description:"Fixture purchase product",item_code:"SKU-TEST",
          quantity:2,unit_price:10,net_value:20,vat_amount:4.8,gross_value:24.8,vat_category:"24",line_type:"product"}]};
      await page.route(url => url.pathname.startsWith("/api/"), async route => {
        const path = new URL(route.request().url()).pathname;
        calls.push(path);
        let response;
        if (path === "/api/auth/me") response = {is_admin:true};
        else if (path === "/api/dashboard/aade-report") response = {data:{aade:{summary,documents:[],mismatches:[]}}};
        else if (path === "/api/dashboard/aade-documents") response = {data:{rows:[invoice],categories:[]}};
        else if (path === "/api/dashboard/audit") throw Error("AADE must not request the unrelated marketing audit");
        else if (path === "/api/dashboard/summary") response = {data:{ad_spend:20,opencart_revenue:124,opencart_orders:1,actual_roas:6.2,ga4_purchases:1}};
        else if (path === "/api/dashboard/brand-category") response = {data:{brands:[],categories:[]}};
        else if (path === "/api/dashboard/opencart-sales") response = {data:{daily:[]}};
        else if (path.startsWith("/api/dashboard/")) response = {data:{rows:[]}};
        else throw Error(`Unexpected fixture API ${path}`);
        await route.fulfill({json:response});
      });
      await page.goto(`${process.env.SUPPLIER_PREVIEW_URL || "http://127.0.0.1:5188"}/#aade`);
      await page.getByRole("row").filter({hasText:"MARK-TEST"}).waitFor();
      await page.getByRole("button",{name:"Refresh",exact:true}).waitFor();
      assert(await page.getByRole("button",{name:"Refresh",exact:true}).isEnabled());
      assert(calls.includes("/api/dashboard/aade-report"));
      assert(!calls.includes("/api/dashboard/audit"));
      await page.getByRole("row").filter({hasText:"MARK-TEST"}).getByRole("button").click();
      await page.getByText("Fixture purchase product",{exact:true}).waitFor();
      const downloading = page.waitForEvent("download");
      await page.getByRole("button",{name:"Export lines",exact:true}).click();
      const downloaded = await downloading;
      assert((await fs.readFile(await downloaded.path(),"utf8")).includes("Fixture purchase product"));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:`test-results/aade-report-${width}.png`,fullPage:true});
      await page.getByRole("button",{name:"Dashboard",exact:true}).click();
      await page.getByRole("button",{name:"Refresh",exact:true}).waitFor();
      await page.getByText("Loading reports",{exact:true}).waitFor({state:"hidden"});
      assert(calls.includes("/api/dashboard/product-profitability"));
      assert.deepEqual(errors,[]);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:`test-results/dashboard-report-${width}.png`,fullPage:true});
      await context.close();
    }
  } finally { await browser.close(); }
  console.log("Dashboard reports and isolated fiscal report, invoice details, CSV exports, desktop/mobile passed.");
}
main().catch(error => {console.error(error);process.exitCode=1;});
