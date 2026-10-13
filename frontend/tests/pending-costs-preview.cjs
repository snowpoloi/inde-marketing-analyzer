// Synthetic UI fixtures only. No supplier, AADE or production operations.
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const dist = path.resolve(__dirname, "../dist");
const supplier = {id:"supplier-fixture", code:"PAKKETO", name:"Pakketo / QA", vat_number:"000000000"};
const line = {line_number:"1", item_code:"499-000049", description:"Καρέκλα με συσκευασία 4 τεμαχίων — δοκιμαστική γραμμή",
  line_type:"product", quantity:4, source_unit:"1", unit:"1", net_value:40, vat_amount:9.6,
  invoice_unit_cost_net:10, unit_cost_net:null, product_catalog_id:null, inde_sku:null,
  reasons:["XML product is not linked to an INDE product."], costed:false, ready:false};
const invoice = {id:"invoice-fixture", supplier_id:supplier.id, supplier:supplier.name, issuer_vat:supplier.vat_number,
  date:"2026-10-13", number:"QA / 100", mark:"qa-mark", source_digest:"a".repeat(64), fingerprint:"b".repeat(64),
  confirm_missing_units:false, needs_unit_confirmation:false, imported:true, can_import:false,
  reasons:[], lines:[line], net_value:40,vat_amount:9.6,gross_value:49.6,ready_lines:0,pending_lines:1,costed_lines:0};
const missing = {...invoice,id:"summary-fixture",number:"QA / 101",lines:[],
  reasons:["Book / VAT summaries are not product invoices."], pending_lines:0};
let accepted = false;
http.createServer(async (req,res)=>{
  const url = new URL(req.url,"http://localhost");
  const json = data=>{res.setHeader("Content-Type","application/json");res.end(JSON.stringify(data));};
  try {
    if (url.pathname.startsWith("/api/")) {
      if (req.method === "POST" && url.pathname.endsWith("/confirm-line")) {
        let body="";for await (const chunk of req) body+=chunk;
        const payload=JSON.parse(body);
        if (payload.product_catalog_id!=="product-fixture" || !payload.confirm_products_and_units || "net_unit_cost" in payload) {
          res.statusCode=409;return json({detail:"Invalid fixture confirmation"});
        }
        accepted=true;return json({data:{costs_created:1,pending_lines:0,duplicate:false}});
      }
      if (req.method!=="GET") {res.statusCode=405;return json({detail:"Fixture rejects writes"});}
      if (url.pathname==="/api/auth/me") return json({id:"fixture",email:"fixture@example.test",is_admin:true});
      if (url.pathname.endsWith("/refresh-state")) return json({feeds:[],cost_revisions:{},sync_revision:null});
      if (url.pathname.endsWith("/period-summary")) return json({rows:[]});
      if (url.pathname==="/api/supplier-catalog/products") return json({rows:[],total:0,categories:[],summary:{products:0,matched:0,unmatched:0}});
      if (url.pathname.endsWith("/identities")) return json({data:{rows:[supplier]}});
      if (url.pathname.endsWith("/pending-costs")) return json({data:{invoices:accepted?[missing]:[invoice,missing],total:accepted?1:2,offset:0,limit:10}});
      if (url.pathname.endsWith("/catalog-search")) return json({data:{rows:[{product_catalog_id:"product-fixture",product_id:"1",sku:"499-000049",model:"499-000049",name:"Καρέκλα Parker — σετ τεσσάρων τεμαχίων",method:"manual_search",confidence:0}]}});
      return json({data:{rows:[]}});
    }
    const filename=path.resolve(dist,`.${url.pathname==="/"?"/index.html":url.pathname}`);
    if (!filename.startsWith(dist+path.sep)) {res.statusCode=404;return res.end();}
    let content=await fs.readFile(filename);
    const ext=path.extname(filename);
    res.setHeader("Content-Type",{".html":"text/html",".js":"text/javascript",".css":"text/css"}[ext]||"application/octet-stream");
    if (ext===".html") content=content.toString().replace("<head>",'<head><script>localStorage.setItem("inde_token","pending-costs-fixture")</script>');
    res.end(content);
  } catch (err) {res.statusCode=500;json({detail:err.message});}
}).listen(5196,"127.0.0.1",()=>console.log("Pending costs QA: http://127.0.0.1:5196/#supplier-catalog"));
