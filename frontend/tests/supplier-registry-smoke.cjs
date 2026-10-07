// Fixture-only registry import: no production records or credentials.
const assert = require("node:assert/strict");
const { mkdir } = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  await mkdir("test-results", {recursive:true});
  const browser = await chromium.launch({headless:true,channel:"chrome"});
  try {
    for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
      const context = await browser.newContext({viewport});
      await context.addInitScript(()=>localStorage.setItem("inde_token","isolated-fixture"));
      const page = await context.newPage();
      const errors=[]; page.on("pageerror",error=>errors.push(error.message));
      let imported=false, imports=0, invoiceRequests=0;
      const base = {code:null,name_pending:false,identity_conflict:false,source:"AADE",documents:4,period_documents:2,last_document_date:"2026-10-01"};
      const rows = [
        {...base,id:"megapap",code:"MEGAPAP",vat_number:"123456789",name:"MEGAPAP verified supplier",source:"Registered"},
        {...base,id:null,vat_number:"987654321",name:"Supplier company imports household goods and professional equipment corporation"},
        {...base,id:null,vat_number:"012345678",name:"AFM 012345678",name_pending:true},
        ...Array.from({length:51},(_,i)=>({...base,id:null,vat_number:String(200000000+i),name:`Supplier ${i}`}))
      ];
      await page.route(url=>url.pathname.startsWith("/api/"),async route=>{
        const url = new URL(route.request().url()); const path=url.pathname;
        let response;
        if (path==="/api/auth/me") response={is_admin:true};
        else if (path==="/api/suppliers/aade/suppliers") {
          assert(url.searchParams.has("date_from") && url.searchParams.has("date_to"));
          response={data:{rows:rows.map(row=>({...row,id:row.id || (imported ? `s-${row.vat_number}`:null),code:row.code || (imported ? `AADE_${row.vat_number}`:null)})),skipped_records:2}};
        } else if (path==="/api/suppliers/aade/suppliers/import") {
          assert.equal(route.request().method(),"POST"); imports++;
          response={data:{created:imported?0:53,existing:imported?54:1,names_updated:0,conflicts:0,skipped_records:2}}; imported=true;
        } else if (path==="/api/suppliers/identities") response={data:{rows:rows.map(row=>({...row,id:row.id || `s-${row.vat_number}`,code:row.code || `AADE_${row.vat_number}`}))}};
        else if (path==="/api/suppliers/aade/invoices") {
          invoiceRequests++; assert.equal(url.searchParams.get("supplier_id"),"s-987654321");
          response={data:{rows:[{id:"d1",date:"2026-10-01",mark:"fixture",number:"INV-1",invoice_type:"1.1",record_type:"full_document",net_value:100,gross_value:124,cancelled:false}],total:1}};
        } else if (path==="/api/suppliers/summary") response={data:{suppliers:imported?54:1,purchases:0,freight:0,matched_products:0,unmatched_products:0,products_with_cogs:0}};
        else if (["/api/suppliers/products","/api/suppliers/unmatched","/api/suppliers/performance"].includes(path)) response={data:{rows:[]}};
        else throw Error(`Unexpected API ${path}`);
        await route.fulfill({json:response});
      });
      await page.goto(`${process.env.SUPPLIER_PREVIEW_URL || "http://127.0.0.1:5188"}/#suppliers`);
      await page.getByRole("button",{name:"Suppliers",exact:true}).click();
      const registry=page.getByRole("region",{name:"Supplier registry",exact:true});
      await registry.getByText("MEGAPAP verified supplier",{exact:true}).waitFor();
      assert(await registry.getByRole("button",{name:"View invoices 987654321"}).isDisabled());
      await registry.getByRole("button",{name:"Next suppliers",exact:true}).click();
      assert.equal(await registry.getByText("MEGAPAP verified supplier",{exact:true}).count(),0);
      await registry.getByRole("button",{name:"Previous suppliers",exact:true}).click();
      await registry.getByRole("button",{name:"Add AADE suppliers",exact:true}).click();
      await registry.getByRole("status").getByText(/53 suppliers added/).waitFor();
      await registry.getByText("54 registered / 54 total",{exact:true}).waitFor();
      assert.equal(imports,1); assert(await registry.getByRole("button",{name:"View invoices 987654321"}).isEnabled());
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Registry page overflows");
      await page.screenshot({path:`test-results/supplier-registry-${viewport.width}.png`,fullPage:true});
      await registry.getByLabel("Search supplier registry").fill("987654321");
      assert.equal(await registry.getByText("MEGAPAP verified supplier",{exact:true}).count(),0);
      await registry.getByRole("button",{name:"Add AADE suppliers",exact:true}).click();
      await registry.getByRole("status").getByText(/0 suppliers added; 54 already registered/).waitFor();
      assert.equal(imports,2);
      await registry.getByRole("button",{name:"View invoices 987654321"}).click();
      const costs=page.getByRole("region",{name:"AADE purchase costs",exact:true});
      await costs.getByRole("button",{name:"Review invoice INV-1",exact:true}).waitFor();
      assert(invoiceRequests>=1 && invoiceRequests<=2,"View invoices must load the selected supplier automatically (StrictMode may repeat the mount)");
      assert.equal(await costs.getByLabel("AADE supplier").inputValue(),"s-987654321");
      assert.deepEqual(errors,[]);
      await context.close();
    }
  } finally { await browser.close(); }
  console.log("AADE supplier registry import, search, pagination, invoice navigation and desktop/mobile checks passed.");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
