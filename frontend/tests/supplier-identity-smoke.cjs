// Fixture-only save: a successful PUT must not wait for another identity listing.
const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  const browser = await chromium.launch({headless:true, channel:"chrome"});
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({viewport:{width,height:900}});
      await context.addInitScript(() => localStorage.setItem("inde_token", "isolated-fixture"));
      const page = await context.newPage();
      const errors = []; page.on("pageerror", error => errors.push(error.message));
      let saved = false, puts = 0, postSaveGets = 0;
      const supplier = {id:"supplier",code:"AADE_084146750",name:"AFM 084146750",vat_number:"084146750"};
      await page.route(url => url.pathname.startsWith("/api/"), async route => {
        const path = new URL(route.request().url()).pathname;
        let response;
        if (path === "/api/auth/me") response = {is_admin:true};
        else if (path === "/api/suppliers/identities" && route.request().method() === "PUT") {
          puts++; saved = true;
          const payload = route.request().postDataJSON();
          assert.equal(payload.vat_number, supplier.vat_number);
          response = {data:{...supplier, ...payload}};
        } else if (path === "/api/suppliers/identities") {
          if (saved) { postSaveGets++; await route.abort(); return; }
          response = {data:{rows:[supplier]}};
        } else if (path === "/api/supplier-catalog/feeds") response = [];
        else if (path === "/api/settings/integrations" || path === "/api/settings/opencart/order-statuses") response = [];
        else throw Error(`Unexpected fixture API ${path}`);
        await route.fulfill({json:response});
      });
      await page.goto(`${process.env.SUPPLIER_PREVIEW_URL || "http://127.0.0.1:5188"}/#settings`);
      const panel = page.getByRole("region", {name:"Supplier identities",exact:true});
      await panel.getByLabel("Supplier identity", {exact:true}).selectOption(supplier.code);
      await panel.getByLabel("Company name", {exact:true}).fill("Verified supplier name");
      await panel.getByRole("button", {name:"Save supplier",exact:true}).click();
      await panel.getByRole("status").getByText("Supplier AFM and company name saved.").waitFor();
      assert(await panel.getByRole("button", {name:"Save supplier",exact:true}).isEnabled());
      assert.equal(await panel.getByLabel("Company name").inputValue(), "Verified supplier name");
      assert.equal(puts, 1); assert.equal(postSaveGets, 0); assert.deepEqual(errors, []);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await panel.screenshot({path:`test-results/supplier-identity-${width}.png`});
      await context.close();
    }
  } finally { await browser.close(); }
  console.log("Supplier name save completes from its acknowledgement without a second GET; desktop/mobile passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
