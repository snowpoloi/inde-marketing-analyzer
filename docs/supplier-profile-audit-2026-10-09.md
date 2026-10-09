# Supplier Profile And Schedule Audit - 2026-10-09

## Evidence And Scope

Sources: owner's `live profiles.zip` (33 profiles), the owner's Plesk Scheduled
Tasks screenshot dated 2026-10-09 13:38:05 (93 tasks shown), and the local XML
snapshots described in `supplier-feed-audit-2026-10-08.md`.

The PHP configuration files were parsed as literal data, never executed. All 33
parsed successfully. Original configuration data, private URLs and credentials
remain outside Git. This report contains no authentication values or feed URLs.
No application code, production settings, prices, categories, cron jobs or
financial records were changed during this audit.

Schedules below are transcribed as displayed by Plesk. Its server timezone was
not shown and has not been verified. Green schedule icons are interpreted as
enabled tasks; this is not evidence of successful execution or job duration.
Profiles absent from the screenshot are marked not shown, not proven unused.

## Important Conclusions

1. The screenshot resolves the three version choices: scheduled profiles are
   `KANELLOPOULOS_NEW_30_5_25`, `ARLIGHT_30_5_25`, and `LIBERTA_30_5_25`.
   Alternative profiles in the ZIP must not be selected just because their names
   include NEW or because they appear newer.
2. SPM and Mastershop are separate sources. SPM uses `api.spm-network.com` and
   prefixes the OpenCart model with `sp.`. Mastershop uses `www.mastershop.gr`
   and retains its reference without that prefix. This resolves the provisional
   combined Mastershop/SPM row in the 2026-10-08 audit.
3. Gloria uses uppercase `GL.` on `product@id` for OpenCart model, while SKU is
   unprefixed `code`. Preserve original case and the original supplier code.
4. Printezis is represented by `PAM&amp;CO.cfg`: its source host is
   `printezis.com`, and the scheduled profile is `PAM&CO` at 07:45. There is no
   need to request a separate Printezis profile merely because of its filename.
5. The Pakketo profile contains two multiplies on `retail_price_with_vat` with
   `sell_step`: functions 14 and 17, with rounding between them. Function 17
   additionally contains the literal value `se`. This is suspicious, not proof
   of an actual shop-price error: plugin operand precedence and current runtime
   behavior were not executed or inspected. Do not reproduce this rule blindly.
6. The scheduled Kanellopoulos profile multiplies regular and offer prices by
   `minimum_quantity`; the alternative NEW XML profile does not. This materially
   affects the sale-unit basis. Zero minimums must not produce a free product or
   a calculated margin. The feed snapshot contains 12 zero minimums.
7. The ZIP already contains 3,282 category-binding entries across all versions.
   They are not 3,282 unique categories: alternate profiles and supplier segments
   overlap. Every binding has a source label. Target values are OpenCart category
   IDs, not a complete target hierarchy with names.
8. Plesk calls `METAXAKIS` at 05:45. The supplied file is
   `METAXAKIS_NEW_01_06_25.cfg`, with import label `METAXAKIS_NEW`. Same supplier
   is plausible, but the actual scheduled configuration has not been proven
   identical. Obtain the scheduled profile before treating it as authoritative.

## Supplier Mapping Matrix

These are configured OpenCart targets, not verified matches against every live
shop product. `model` and `sku` are separate columns. `item_identifier=model`
means the resulting OpenCart model, not necessarily the XML field named model.
An exact unique model/SKU match still needs the correct supplier identity/AFM.

| Supplier / Selected Profile | Configured OpenCart Model | Configured OpenCart SKU | Regular Price Rule Observed | Sale Unit / Main Caveat | Schedule Shown |
| --- | --- | --- | --- | --- | --- |
| MEGAPAP | XML `sku` | XML `sku` | `retail_price_with_vat / 1.24 * minimum`, round 4 | Owner-confirmed sale set; AADE code links via XML `model`, not XML `sku`. Keep the two supplier identifiers. | Hourly :35 |
| Pakketo / PAKOWORLD | `model` | `model` | Divide retail by 1.24, multiply by `sell_step`, round 4, then another multiply appears | Owner-confirmed set price at INDE. Investigate duplicate multiply; never apply the set factor twice in analyzer. | Hourly :29 |
| Anthemidis | `product_sku` | `product_sku` | `Web_price`: round 2 then divide 1.24 | Maps minimum from `min_order_level`, but skips values > 1. Stock < 2 excluded. Literal XML header row must be excluded. | Hourly :20 |
| Arlight / ARLIGHT_30_5_25 | `Sku` | `Sku` | `percentage(20, Price)` into an extra field | Special price uses `Price`. No explicit VAT division in inspected price functions; do not invent price basis from the field name. | Daily 02:20 |
| Buyway | `BW.` + `SKU` | `SKU` | `RetailPrice / 1.24` | `InStock=N` skipped. Tier quantity is not a declared sale multiplier. | Hourly :17 |
| Daisat | `dai.` + `sku`, written into source `id` by transform | `sku` | `price_retail_untaxed` | Margin filter uses retail/wholesale net difference. Repeated category rows must be consolidated without adding prices/stock. | Daily 08:30 |
| Getters | `g.` + `sku` | `sku` | `price / 1.24` | Feed is the supplied Zipro/Sense7/Peme subset; not proof of all Getters products. | `1-56/4 * * * *` |
| Gloria | `GL.` + `product@id` | `code` | `percentage(-15, priceSuggested)`, divide 1.24, round 0 | Barcode is not universally reliable. Several sets/description patterns and empty images excluded. | Daily 22:00 |
| Kanellopoulos / KANELLOPOULOS_NEW_30_5_25 | `SKU` | `SKU` | `LIANIKH / 1.24`, round 2, then multiply `minimum_quantity` | Offer follows same set factor. Different rule from the alternative profile. Validate nonzero units against actual product/invoice. | Daily 03:15 |
| Liberta / LIBERTA_30_5_25 | `Lib.` + `sku` | `sku` | Regular price maps `retail-price` unchanged in inspected functions | Special uses `discounted-price / 1.24`, with fallback. Skips `minimum-quantity > 1`. Do not use negative `packing` as sale step. | Daily 03:40 |
| Metaxakis / candidate supplied profile | `me.` + `code` | `code` | `minimum_retail_price / 1.24` | Candidate profile only; cron calls a different profile name. Repeated category rows must not inflate totals. | METAXAKIS daily 05:45 |
| Printezis / PAM&CO | `pa.` + `sku` | `sku` | `reg_price / 1.24`; offer `sale_price / 1.24` | Profile skips `minimum_quantity=2`, although no such field was found in supplied XML snapshot. Missing field behavior needs verification. | Daily 07:45 |
| Mastershop | `reference` | `reference` | `price * 2 / 1.24`, round 2; `percentage(25, price)` into `location` supplies regular price | Special uses transformed `price`. No `sp.` prefix. EAN target is reference, not the actual `ean13` feed field. | Daily 00:30 |
| SPM | `sp.` + `sku` | `sku` | Regular `arxiki_timi`; special `lianiki / 1.24`, percentage 5, round 4 | Different feed from Mastershop; source XML not among the 13 feeds fetched on 2026-10-08. | Hourly :40 |

`percentage(...)` above records the configured plugin operation and operand,
not a reimplementation of its undocumented semantics. The archive is not the
plugin source. These rules describe shop imports, not actual purchase costs.

## Complete Uploaded Profile Inventory

`Bindings` counts configured source-category binding entries, not target category
IDs or products. IDs/SKUs below are after the visible identifier transforms.
The floor-lighting profile is listed with an English alias for its Greek filename.

| Uploaded Profile | Model Target | SKU Target | Regular Price Source | Bindings | Scheduled Evidence |
| --- | --- | --- | --- | ---: | --- |
| SPM.cfg | `sp.` + sku | sku | arxiki_timi | 578 | Hourly :40 |
| VENCORE.cfg | `vn.` + sku | sku | retail_price_no_vat | 80 | Hourly :12 |
| cokitex-oikiako.cfg | model | sku | wholesale_price | 0 | Not shown under this name |
| ROYAL CARPET NEW 19_10_22.cfg | upc | upc | price | 5 | Daily 20:30; identifier is name, not model |
| DAISAT_NEW_30_5_25.cfg | `dai.` + sku | sku | price_retail_untaxed | 0 | Daily 08:30 |
| PAKOWORLD.cfg | model | model | retail_price_with_vat | 248 | Hourly :29 |
| MEGAPAP.cfg | sku | sku | retail_price_with_vat | 70 | Hourly :35 |
| GLORIA_30_5_25.cfg | `GL.` + product@id | code | extra field from priceSuggested | 149 | Daily 22:00 |
| LIBERTA_30_5_25.cfg | `Lib.` + sku | sku | retail-price | 467 | Daily 03:40 |
| KANELLOPOULOS_NEW_30_5_25.cfg | SKU | SKU | LIANIKH | 147 | Daily 03:15 |
| GETTERS.cfg | `g.` + sku | sku | price | 50 | Every fourth minute within 1..56 |
| SUPERGREEN_NEW_30_5_25.cfg | id | barcode | b2c_price | 25 | Daily 00:00 |
| BUYWAY.cfg | `BW.` + SKU | SKU | RetailPrice | 93 | Hourly :17 |
| KANELLOPOULOS - NEW XML.cfg | SKU | SKU | LIANIKH | 166 | Alternative not shown |
| ARLIGHT_30_5_25.cfg | Sku | Sku | extra field from Price | 58 | Daily 02:20 |
| ELOBRA.cfg | `el.` + kodikos | kodikos | timi_katalogou | 1 | Daily 07:20 |
| FISHER.cfg | `fs.` + kodikos | kodikos | timi_katalogou | 21 | Daily 07:30 |
| METAXAKIS_NEW_01_06_25.cfg | `me.` + code | code | minimum_retail_price | 57 | Related METAXAKIS task 05:45; identity pending |
| ANTHEMIDIS_NEW_31_5_25.cfg | product_sku | product_sku | Web_price | 183 | Hourly :20 |
| PAM&amp;CO.cfg | `pa.` + sku | sku | reg_price | 34 | PAM&CO daily 07:45; source Printezis |
| ESTIA NEW.cfg | `ES.` + SKU | SKU | PriceRetail | 97 | Daily 01:40 |
| COKITEX_TELIKO_8_3_22.cfg | `co.` + mpn | mpn | sale_price | 32 | Daily 08:25 |
| ZOUGRIS_30_5_25.cfg | Code | Code | WholesalePrice | 49 | Daily 05:30 |
| ZOUGRIS_SIESTA.cfg | Code | Code | WholesalePrice | 49 | Daily 05:45 |
| HEAD.cfg | `io.` + sku | sku | sale_price | 10 | Daily 00:20 |
| ZOGGS.cfg | `io.` + sku | sku | sale_price | 9 | Daily 00:25 |
| TECH-PRO.cfg | `io.` + sku | sku | sale_price | 20 | Daily 00:27 |
| MASTERSHOP_NEW_NO_CAT_30_5_25.cfg | reference | reference | location derived from price | 247 | Daily 00:30 |
| PLASTONA_NEW_30_5_25.cfg | reference | reference | price | 41 | Daily 05:05; same source host as Mastershop |
| MEGAPAP floor lighting | sku | sku | retail_price_with_vat | 1 | Daily 09:10; separate segment |
| MARES.cfg | `io.` + sku | sku | sale_price | 0 | Daily 00:10 |
| ARLight New.cfg | Sku | Sku | extra field from Price | 55 | Alternative not shown |
| LIBERTA.cfg | `Lib.` + sku | sku | retail-price | 240 | Alternative not shown |

There are 28 uploaded profiles with corresponding enabled scheduled names after
space/underscore and HTML-entity display normalization. One further candidate
(Metaxakis) needs verification, and four alternatives have no corresponding name
shown. This is not a claim that every enabled task succeeds or that all 33 files
are distinct suppliers. For example, HEAD/ZOGGS/TECH-PRO/MARES share source host
`www.ionas.gr`, and Mastershop/Plastona share a source host.

The screenshot also contains profiles not supplied in this ZIP, including
`LIBERTA_QUICK_EMPORIO` at 03:55 and `COKITEX_HOTEL` at 20:45. Liberta's later
quick update could affect final shop prices; do not assume the 03:40 full import
is the final price writer. `cokitex-oikiako.cfg` is not proven to be COKITEX_HOTEL.
Several DES/seasonal jobs have grey icons; do not activate them or import their
rules merely because they appear in the schedule list.

## Price, Stock And Package Risks

- Pakketo functions 14 and 17 both target the regular-price field. Existing
  analyzer rules multiply AADE per-piece cost by the sale step only once and keep
  the already-per-set gross INDE price unchanged. Preserve that behavior.
- MEGAPAP's separate floor-lighting profile maps OpenCart minimum from XML minimum
  and divides the retail price by 1.24 without the main profile's price multiplier.
  The main profile has a floor-lighting delete rule. These are separate scheduled
  segments, not two interchangeable versions to run over the same full catalog.
  Segment membership and overlapping updates need explicit checks.
- Zougris general profile applies a percentage operand `-25%`, multiplier 1.4,
  rounding and a later `Package` multiplier. SIESTA instead has percentage `-36`,
  multiplier 1.4, and maps OpenCart minimum from `Package`. Do not unify both price
  formulas or infer sale-unit conversions for all products from one profile.
- Liberta's regular price and discounted price have different visible transforms;
  Arlight uses a percentage operation without explicit VAT division. Compare with
  the actual INDE export before assigning a tax basis to these supplier prices.
- Blank quantity mappings (for example Buyway and PAM&CO), availability text, and
  profile defaults do not establish a physical stock number. Keep these distinct.
- Royal Carpet's matching identifier is name. A title-based shop-import key must
  not become an automatic financial matching rule for invoice lines.
- Profile shipping calculations sometimes extract dimensions from descriptions,
  substitute 1 for missing axes, then divide the volume product by 5,000. Such
  fallback dimensions are not measured parcels. Keep unavailable package axes
  unknown in the analyzer; do not inherit guessed shipping values.
- Current out-of-stock and skip rules are shop eligibility rules. Retain historical
  catalog identities for matching past invoices even when no longer eligible for
  display/import into the shop.

## Categories And Financial Confidence

Use paired `col_binding_names` and `col_binding` entries to retain original
supplier categories and corresponding OpenCart IDs. Extra unbound source labels
exist, including two in MEGAPAP. Preserve their unmapped status rather than
inventing an INDE category. An OpenCart category ID/name/parent export is needed
only to display the target hierarchy by name, not to perform product-cost matching.

Confidence is split by evidence, not expressed as an invented percentage:

- Configured identifier mapping: directly observed for all uploaded profiles.
- Scheduled version: observed for 28; Metaxakis candidate and four unscheduled
  alternatives remain distinct.
- Actual unique OpenCart product match: requires a dry-run against the current shop
  export, checking both model and SKU and rejecting duplicate candidates.
- Actual purchase price: requires a supplier-AFM-scoped, noncancelled AADE invoice
  line with quantity, net value, discounts/credits and verified sale-unit mapping.
  An XML retail/wholesale field is not proof of actual purchase cost.

Retain invoice codes without shop prefixes; join invoice -> supplier XML record ->
unique OpenCart record. Titles can suggest candidates for review, not authorize
cost acceptance. Treat margin as product gross margin before shipping, advertising
and other overhead; do not label it exact final profit.

## Implementation Handoff

1. Use the selected scheduled profiles and preserve the mapping inventory above.
   Verify METAXAKIS and obtain LIBERTA_QUICK_EMPORIO before final-price parity
   testing. Do not block unrelated supplier adapters on these two exceptions.
2. Investigate the Pakketo duplicate multiplier by checking the plugin's operation
   semantics and a regular-price set example, without altering the shop silently.
3. Add declarative read-only adapters, scoped exact identifier matches and dry-run
   output. Never execute PHP profiles or transplant insert/update/delete actions.
4. Keep catalog data and category mapping separate from approved AADE costs.
   Preserve the actual gross INDE sale price and calculate net comparisons once.
5. Use bounded sequential/staggered refresh jobs, atomic snapshot replacement,
   last-good data on errors and deduplication across feed segments. Do not blindly
   copy the shop's cron frequency to the analyzer.

Getters' displayed expression produces 14 scheduled starts per hour (minutes 1,
5, ..., 53), up to 336 per day if enabled continuously. Other hourly suppliers
also run during daily imports. This suggests a workload worth measuring, but
does not establish the cause of the analyzer's past CPU or loading problems:
execution logs, duration, server topology and resource measurements are missing.
Do not change schedules or upgrade hardware based on this screenshot alone.

## Implemented Scope And Verification

After the audit, the owner approved proceeding without Metaxakis and Liberta.
Ten read-only adapters were added, retaining MEGAPAP and Pakoworld support.
The selected profile category bindings were converted to declarative data only:
1,853 normalized labels, with one conflicting binding retained as ambiguous.
The original private feed URLs and executable PHP configurations are not committed.

Cached real-source parsing results on 2026-10-09:

| Adapter | Unique Products | Diagnostics |
| --- | ---: | --- |
| Anthemidis | 2,073 | One header excluded; two source names absent |
| Arlight | 1,459 | Two non-product Offer/Credit rows excluded |
| Buyway | 619 | No duplicate product codes |
| Daisat | 1,679 | 157 repeated category memberships merged without adding stock |
| Getters | 379 | Supplied subset only |
| Gloria | 1,629 | Component-set sale quantities remain unresolved |
| Kanellopoulos | 2,133 | One source name absent; invalid minimums block margins |
| Printezis / PAM&CO | 1,226 | No guessed physical stock |
| Mastershop | 10,452 | Separate source from SPM |
| SPM | 7,475 | HTTPS source fetched successfully on 2026-10-09 |

Verification: 291 backend tests passed against a fresh isolated PostgreSQL database;
frontend type checking and production build passed; desktop (1440px) and mobile
(390px) browser tests passed. Tests cover each adapter's atomic worker import,
retaining last-good snapshots, host/auth redirect restrictions, missing fields,
category conflicts, prefixed identity matching and AADE sale-set price calculations.
Private credential values from the audited profiles were checked against tracked
and unignored working files, with no matches. This is not an audit of all Git history.

These tests do not establish live production feed configuration, supplier AFMs,
or purchase-unit consent for newly added suppliers. Those remain separate from
format support and must not be fabricated from a trading name or XML URL.
