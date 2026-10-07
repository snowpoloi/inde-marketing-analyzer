// Local fixture-only checks; no production invoices are accepted.
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  await mkdir("test-results", { recursive: true });
  const browser = await chromium.launch({ headless:true, channel:"chrome" });
  try {
    for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
      const context = await browser.newContext({viewport});
      await context.addInitScript(() => localStorage.setItem("inde_token","isolated-fixture"));
      const page = await context.newPage();
      const errors = []; page.on("pageerror",error => errors.push(error.message));
      let saved = false, imported = false;
      const supplier = {id:"s1",code:"MEGAPAP",name:"MEGAPAP Supplier Company Imports Trade Household Goods and Professional Equipment Corporation",vat_number:"123456789"};
      const invoice = {id:"d1",date:"2026-09-01",mark:"400-test",invoice_type:"1.1",number:"A/INV-1",
        net_value:145,gross_value:179.8,cancelled:false,record_type:"full_document"};
      const preview = { ...invoice, supplier_id:"s1",supplier:supplier.name,issuer_vat:supplier.vat_number,
        vat_amount:34.8,fingerprint:"a".repeat(64),reasons:[],can_import:true,imported:false,lines:[
          {line_number:"1",item_code:"0268292",description:"Garden chair polypropylene grey 56x60x86.5 cm",
            inde_sku:"CH-N5080-GR",line_type:"product",quantity:2,unit:"1",unit_cost_net:70,net_value:140,vat_amount:33.6,reasons:[]},
          {line_number:"2",item_code:"",description:"Shipping",inde_sku:null,line_type:"shipping",quantity:null,
            unit:"",unit_cost_net:null,net_value:5,vat_amount:1.2,reasons:[]}]};
      await page.route(url => url.pathname.startsWith("/api/"),async route => {
        const path = new URL(route.request().url()).pathname;
        let response;
        if (path.endsWith("/auth/me")) response = {is_admin:true};
        else if (path === "/api/suppliers/identities") {
          if (route.request().method() === "PUT") { assert.equal(route.request().postDataJSON().vat_number,"123456789"); saved=true; response={data:supplier}; }
          else response={data:{rows:[supplier]}};
        } else if (path.endsWith("/suppliers/summary")) response={data:{suppliers:1,purchases:imported?140:0,freight:imported?5:0,matched_products:0,unmatched_products:0,products_with_cogs:0}};
        else if (["/api/suppliers/products","/api/suppliers/unmatched","/api/suppliers/performance"].includes(path)) response={data:{rows:[]}};
        else if (path === "/api/suppliers/aade/invoices") response={data:{total:1,rows:[invoice]}};
        else if (path === "/api/suppliers/aade/invoices/d1") response={data:{...preview,can_import:!imported,imported,reasons:imported?["Invoice already imported; no second financial copy will be created."]:[]}};
        else if (path.endsWith("/d1/accept")) {
          const body=route.request().postDataJSON(); assert.equal(body.confirm_products_and_units,true);
          assert.equal(body.fingerprint,preview.fingerprint); assert.equal(Object.keys(body).length,3);
          imported=true; response={data:{duplicate:false,costs_created:1}};
        } else if (["/api/settings/integrations","/api/settings/opencart/order-statuses","/api/supplier-catalog/feeds"].includes(path)) response=[];
        else throw Error(`Unexpected API ${path}`);
        await route.fulfill({json:response});
      });
      await page.goto(`${process.env.SUPPLIER_PREVIEW_URL || "http://127.0.0.1:5187"}/#settings`);
      await page.getByRole("heading",{name:"Supplier identities",exact:true}).waitFor();
      const registry=page.getByRole("region",{name:"Supplier identities"});
      await registry.getByLabel("Supplier identity",{exact:true}).selectOption("MEGAPAP");
      await registry.getByRole("button",{name:"Save supplier"}).click();
      await registry.getByText("Supplier AFM and company name saved.").waitFor(); assert(saved);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.getByRole("button",{name:"Suppliers & COGS",exact:true}).click();
      await page.getByRole("button",{name:"AADE costs",exact:true}).click();
      await page.getByLabel("AADE supplier").selectOption("s1");
      await page.getByRole("button",{name:"Load invoices"}).click();
      await page.getByRole("button",{name:"Review invoice A/INV-1"}).click();
      await page.getByText("CH-N5080-GR",{exact:true}).waitFor();
      assert(await page.getByRole("button",{name:"Accept AADE costs"}).isDisabled());
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),"AADE page overflows");
      await page.screenshot({path:`test-results/supplier-aade-${viewport.width}.png`,fullPage:true});
      await page.getByLabel("Verified products; one purchase piece equals one INDE sales unit").check();
      await page.getByRole("button",{name:"Accept AADE costs"}).click();
      await page.getByText("1 AADE product costs saved.").waitFor();
      assert(imported); assert.equal(await page.getByRole("button",{name:"Accept AADE costs"}).count(),0);
      await page.getByRole("button",{name:"Supplier AFM settings"}).click();
      await page.getByRole("heading",{name:"Supplier identities",exact:true}).waitFor();
      assert.deepEqual(errors,[]); await context.close();
    }
  } finally { await browser.close(); }
  console.log("Supplier identity and AADE review desktop/mobile checks passed.");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
