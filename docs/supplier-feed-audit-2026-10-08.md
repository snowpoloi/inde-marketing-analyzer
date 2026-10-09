# Supplier Feed Audit - 2026-10-08

Follow-up: `supplier-profile-audit-2026-10-09.md` records the 33 supplied import
profiles and the owner's Plesk schedule screenshot. It resolves the provisional
Mastershop/SPM grouping below as two separate feeds, identifies Printezis as
PAM&CO, and refines the shop identifier and active-profile mappings. The XML
counts in this document remain the 2026-10-08 snapshot.

## Scope And Result

Read-only retrieval and structured XML inspection of all 13 supplier feeds provided
by the owner. All 13 returned HTTP 200 and parseable XML. No application code,
production settings, catalog records, OpenCart data, invoice data or costs were
changed. Downloads were sequential and ran locally, not on the production server.

Private feed URLs, credentials and downloaded XML remain outside the repository.
This document deliberately contains no URLs, tokens or passwords. Counts are a
point-in-time feed snapshot, not counts of products already linked to INDE.

Only MEGAPAP and Pakketo currently have supported application adapters. Successful
retrieval of another feed does not mean that its ingestion or financial matching
is implemented or approved.

## Mapping Matrix

Every proposed shop match below is pending verification against the actual
Geekodev Import/Export Pro profile. A unique supplier identifier is not proof of a
unique OpenCart match. Supplier identity/AFM and exact invoice-line mapping must
also be verified before using AADE costs.

| Supplier | XML records | Candidate stable identifier | Prices found | Units and categories | Match readiness |
| --- | ---: | --- | --- | --- | --- |
| Anthemidis | 2,074 | `product_sku`; `product_gtin` secondary | `pricewithouttax`, `Web_price`, `neth-price` | `min_order_level`; `category_path` | 2,073 real rows plus one literal header row. Confirm profile SKU and sale-unit rules. |
| Arlight | 1,461 | `Sku`, with source `ID` retained | `Price`, `RegularPrice`, `SalePrice`, `retail-price-with-vat`, `retail-price-final` | WooCommerce export categories and attributes | 1,459 unique populated SKUs; two published records named Offer/Credit have no SKU. |
| Buyway | 619 | `SKU`; `Barcode` secondary; retain `ProductId` | `TierPrices/TierPrice/Price`, `RetailPrice`, `RecyclingCost` | Tier `Quantity` must not be treated as sale step; `Category` | SKU unique throughout; MPN is not unique. Confirm tier selection and tax basis. |
| Daisat | 1,836 | `sku` plus source `id`; `mpn` secondary | `price_wholesale_untaxed`, `price_retail_untaxed` | `packaging_boxes`, `category_id`, `category_name` | 1,679 unique products by id/SKU. Merge repeated category memberships only after conflict checks. |
| Getters | 379 | `sku`; consistent `ean`/`barcode` secondary; retain `id` | `price`, `list_price`, `Vat` | `quantity`, `category` | Unique SKUs and EANs throughout. VAT rate is 24, but price tax inclusion still needs confirmation. This is the supplied Zipro/Sense7/Peme feed, not proof of the entire Getters catalog. |
| Gloria | 1,629 | Supplier `code`; proposed shop SKU `gl.` + `code` | `priceSuggested`, `priceWholesale` | `set/product_code` identifies components; `category` | Codes unique; owner confirmed INDE prefix `gl.`. Verify the profile uses this exact source field; do not apply the prefix to invoice codes. |
| Kanellopoulos | 2,133 | `Model` / `SKU`; `EAN` secondary | `Price`, `WEBPRICE`, `LIANIKH`, `WEBPRICE_OFFER` | `minimum_quantity`, `Category` | Model and SKU unique. Confirm selected shop-price field and minimum-to-sale conversion. |
| Liberta | 6,029 | `sku`; `barcode` secondary | `retail-price`, `discounted-price`, `emporio-lower-price` | `minimum-quantity`, `packing`, `Boxes`, `categories/item` | SKU and barcode unique. Negative packing values must not become cost multipliers. |
| Metaxakis | 2,867 | `code` plus `product_id` | `price`, `minimum_retail_price` | `pieces`, `category`, `subcategory` | 2,316 unique products. Confirm profile deduplication and the meaning of pieces. |
| Printezis | 1,226 | `sku`; preserve `barcode` as supplier text, not presumed EAN | `reg_price`, `sale_price`, `discount_percentage` | `categories`; no explicit sale-step field found | SKUs unique; barcode repeats the SKU, so it is not an independent EAN identifier. |
| Mastershop / SPM confirmation pending | 10,452 | `reference`; `product_id` retained; `ean13` secondary | `price` | `product_category_tree`; no explicit sale-step field found | References unique. Owner specifies prefix `sp.` for SPM; confirm this feed/profile is SPM before applying it. `supplier_reference` is empty throughout. |
| MEGAPAP | 3,344 | `model` for invoice code; `sku` for INDE SKU | Explicit gross retail/offer and net wholesale fields | `minimum`, `category`, `packages_per_item` | Existing adapter; model/SKU unique. Confirmed per-piece prices and sale-set multiplication, with INDE already priced per set. |
| Pakketo / Pakoworld | 7,958 | `model` for invoice/shop code; `ean` secondary | `retail_price_with_vat`, `weboffer_price_with_vat`, `net_price`, `stock_price` | `sell_step`, `category`, `categories/category`, component fields | Existing adapter; model/EAN unique. Confirmed sale-set rule; two explicit zero sell steps must not generate margins. |

## Important Findings

- Anthemidis has a literal header record (`product_sku = product_sku`,
  `product_name = product_name`, nonnumeric `min_order_level`). It must be excluded
  explicitly. `min_order_level` is populated on only 331 rows, one being this
  header. Missing values do not establish a physical sale quantity. Decimal commas
  are used in price and volume fields. GTIN values are not all unique.
- Arlight has two published non-SKU rows: Offer and Credit. They must not become
  ordinary matched supplier products. `retail-price-with-vat` explicitly labels
  gross retail; a generic `Price` must not be called wholesale cost merely because
  it is lower. WooCommerce `TaxStatus` / `TaxClass` describe tax handling, not by
  themselves the tax basis of every exported price.
- Daisat repeats 134 product IDs, creating 157 additional rows. All repeated
  groups have differing category membership, while inspected SKU, name, prices,
  stock, MPN/EAN, weight, dimensions and package count agree within each group.
  Preserve all category memberships, deduplicate products, and block financial
  imports if economic or identity fields conflict in a later snapshot. Some EAN
  values are short internal codes, so presence alone is not EAN validation.
- Gloria includes barcode/EAN text such as a Greek box prefix, as well as duplicate
  values. Prefer verified supplier code with the shop prefix over unconditional
  EAN matching. Nested set component codes are not a sale-quantity declaration.
- Kanellopoulos has 12 explicit zero `minimum_quantity` entries. Other entries
  include 1, 2, 3, 4, 6, 12 and 24. The owner-confirmed MEGAPAP/Pakketo multiplier
  must not automatically be applied here without the import profile or confirmation.
- Liberta separates sale minimum, packing and box count. `packing` includes
  negative values such as -4 and -12; do not use absolute value as an invented
  conversion. `Boxes` ranges from 0 to 6. Keep the supplier's semantics and obtain
  the actual profile transformation for each field.
- Metaxakis has 540 repeated code groups, producing 551 additional rows. Code
  and product ID both identify 2,316 products. Inspected identity, title, prices,
  stock, pieces, dimensions, volume and weight agree within repeated groups;
  subcategory differs in 74 groups. Merge memberships, not quantities or prices.
  The original endpoint redirects toward HTTP on its canonical host. Retrieval
  succeeded using HTTPS on that host; no token was transmitted over HTTP.
- Printezis `barcode` duplicates its own alphanumeric SKU. It is not an EAN feed.
- Mastershop/SPM dimensions and weight are zero throughout this snapshot. Treat
  them as unavailable, not zero shipping cost or zero-sized packages.
- MEGAPAP has minimum 1 on 3,296 rows, 2 on 27, and 4 on 21. Package count is an
  independent field and reaches 10.
- Pakketo sell step is 1 on 7,511 rows, 2 on 263, 4 on 181, 5 on one, and zero on
  two. Product dimensions and component counts are not shipping-box definitions.

## Shipping Evidence

Product dimensions are not automatically parcel dimensions. The existing courier
divisor remains 5,000, but volumetric calculations need confirmed centimetre parcel
axes and a known number of parcels. Zero or incomplete dimensions stay unknown.

| Supplier | Shipping fields available | Limitation |
| --- | --- | --- |
| Anthemidis | `product_height/length/width/weight`, `kyv_ana_tem`, `product_box` | Confirm product versus packed dimensions and volume units. |
| Arlight | `Length/Width/Height/Weight`, dimension/volume attributes | Sparse data; dimension attributes include diameters, height labels and free text. |
| Buyway | `Length/Width/Height/Weight` | Units and whether these are product or parcel dimensions need confirmation. |
| Daisat | `dimensions_cm`, `WEIGHT` with kg suffix, `packaging_boxes` | Multi-box counts do not supply complete per-box axes in these fields. |
| Getters | `weight` with kg suffix; descriptions | No dedicated structured parcel-axis fields found. |
| Gloria | `mass`, `weight`, `dimension_x/y/z` | Structured axes are zero throughout; no reliable parcel calculation. |
| Kanellopoulos | `Height/Width/Length`, `Weight` with kg suffix | Many zero values; product versus parcel basis must be confirmed. |
| Liberta | `Boxes`, `box1` through `box6`, `volume`, `weight`, `dimensions` | Strong candidate for parcel parsing: boxes contain `mikossysk`, `platossysk`, `ypsossysk`, `Qty`; some axes are missing. Units and per-box quantity semantics still need validation. |
| Metaxakis | `dimensions`, `weight`, `volume`, `pieces` | Do not interpret pieces as sales or parcel count without confirmation. |
| Printezis | Free-text `dimensions` | Product dimensions include diameter/height formats; parcel sizes unavailable. |
| Mastershop/SPM | `height/width/depth/weight` | All zero; retain as missing. |
| MEGAPAP | `packages_per_item`, combined box-labelled cm fields, volume/weight | Existing labelled-box parser; incomplete axes remain unknown. |
| Pakketo | Product dimensions, weight/gross_weight, volume/volume_step | Retain as source metadata, not fabricated per-package measurements. |

## What To Request From Import/Export Pro

Export the existing profiles and category mappings now, not after implementing
all adapters. Remove passwords, private URLs/tokens, admin sessions and API keys.
Keep the mapping and transformation configuration intact, particularly:

1. Source field used for OpenCart SKU, model, EAN and other matching identifiers.
2. Prefixes/suffixes and transformations, including Gloria `gl.` and SPM `sp.`.
3. Price source, VAT handling, discount formulas, rounding and sale-set multipliers.
4. Stock, availability, missing-product, product-status and duplicate-row rules.
5. Category mapping, category creation rules and multi-category handling.
6. Options, variants, component/bundle transformations and packaging mappings.

Use one profile per supplier/feed, including a second profile where the same
supplier has separately configured feed segments. Confirm supplier identity/AFM
from the application's existing identities rather than treating every invoice
issuer as an inventory supplier.

## Proposed Next Step

Use the profiles to finalize a versioned per-supplier mapping. Preserve raw
supplier identifiers separately from transformed shop identifiers, so invoice
matching still uses the original supplier code. Check exact SKU/model/EAN matches
within that supplier and refuse ambiguous/conflicting matches; title similarity
can suggest a candidate but cannot approve a financial match.

Category mapping is not a prerequisite for AADE cost comparison. Store original
supplier categories and mapped INDE categories separately; do not overwrite shop
categories or products as part of the analyzer's read-only sync.

Implement and test each adapter against its real schema, including headers,
duplicates, invalid numbers, missing fields, per-set conversion and host-locked
HTTPS downloads. Credential-bearing URLs need private encrypted storage and
redacted errors; the current adapter rejects embedded basic-auth credentials and
must not be relaxed globally.

Reuse the bounded, single-feed worker with staggered daily refreshes and atomic
snapshots, not 13 concurrent full downloads. Keep previous successful data when a
new feed fails. AADE invoices remain the source of verified actual purchase costs;
XML prices remain supplier list/reference prices, not a cost fallback.
