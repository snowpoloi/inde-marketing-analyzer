# Suppliers, Product COGS And Logistics

## Scope

The Suppliers & COGS page contains supplier product mappings, an unresolved-product review queue, cost history, normalized JSON imports and supplier performance. Administrators can verify mappings, add manual costs, save free-shipping thresholds and simulate a threshold without changing saved settings. Products and Dashboard profitability display realized net product sales, historical COGS, gross profit, margin, source/date/confidence and coverage.

All data is stored in the application's PostgreSQL database. This module makes **no requests or writes to AADE, OpenCart, suppliers or banks**. Linking an existing AADE record is a local database operation, requiring supplier VAT, expense direction, date, amount and document number. It does not submit or cancel invoices.

## Migration

`0008_supplier_cogs`, following `0007_bank_transactions`, adds:

- `suppliers`, `supplier_import_batches`, `supplier_documents`, `supplier_document_lines`.
- `supplier_product_maps`, `supplier_product_costs`, `supplier_shipping_costs`.
- OpenCart line subtotal/discount/tax/total columns and catalog EAN/UPC/MPN columns. Catalog identifiers are backfilled from existing raw JSON. Profitability reads original line JSON so older records do not need a resync merely because the new numeric columns initially contain zero.

The migration is additive. Compose startup already runs `alembic upgrade head`; PostgreSQL migrations use an advisory transaction lock so simultaneous backend/worker startups serialize. No production rows are deleted. Downgrade removes the new supplier data and must only be used intentionally with a backup. Upgrade, downgrade to 0007 and re-upgrade were validated on an isolated PostgreSQL 17 instance.

## Financial Rules

`Gross profit = net product sales - net product COGS`; margin is gross profit divided by net sales. Calculations use Decimal and four decimal places; currency formatting happens at display time. Supplier freight, customer shipping, recoverable VAT and advertising spend are not included in product COGS.

The default sales contract follows native OpenCart: `price` and `total` exclude VAT. `total` includes line-level discounts but not an order coupon. `subtotal` is before line discounts. For exports with VAT-inclusive prices, supply `prices_include_vat: true` and `vat_rate`. Alternatively supply `gross_total` plus `tax_amount` or `vat_rate`. No universal 24% rate is guessed. `net_total` is authoritative after line discounts; set `includes_order_discount: true` if it already includes the order discount. An explicit zero is respected.

Order coupons are distributed proportionally over pre-refund product sales, with a rounding residual assigned once. An explicit line `coupon_share` prevents distributing that discount twice; set `includes_order_discount` if that share is already included in the line total. `coupon_shipping_share`, if supplied on an order, is excluded from the product coupon allocation. Mixed included/not-included discount totals without enough allocation information are unknown rather than estimated.

Line `refund_net` or `refund_gross` reduces revenue. Returned/refunded quantities reduce COGS; an amount-only goodwill refund does not imply inventory was returned. A return without an explicit amount prorates the discounted line revenue. Order-only refund amounts cannot safely be split between products and shipping: those product margins are unknown. Invalid VAT/financial values and non-EUR orders also produce unknown margins.

## Matching And Historical Costs

Priority is: previously verified mapping, exact supplier SKU to OpenCart SKU, exact supplier SKU to model, exact EAN/UPC, exact supplier code. Only one exact candidate at the winning tier may be applied automatically; ties require review. Fuzzy names are suggestions only. Identifier normalization preserves internal whitespace and leading zeros.

MEGAPAP uses `GP041-0025,4` to match the OpenCart model. Internal code `0212605` is retained but not used as an automatic product match. Unit changes require review. Quantities per pack and conversion factors are explicit, positive and persisted on the mapping.

Historical selection only considers active EUR costs dated on or before the order date. Source priority is invoice, supplier order/proforma, pricelist, manual, historical. Within a source tier, latest date wins, then confidence and a stable tie-breaker. Thus a newer pricelist does not override a reliable invoice automatically. Current COGS uses the same policy as of the selected report end date. A sale with no eligible cost has unknown COGS, not zero. Aggregated realized provenance is separate from current cost provenance.

This is **best available historical purchase cost**, not lot-specific inventory valuation, FIFO or a verified supplier-invoice-to-customer-order allocation. Same-day invoices are eligible; no intra-day availability time is invented. Credit notes reduce purchases and freight but do not silently reprice historical product costs. Mapping corrections preserve old amounts as superseded rows and create new cost revisions. Verification and settings changes retain actor/timestamp audit metadata; imports retain batch, source reference, filename, hash and import actor.

## Import Safety And Supplier KPIs

Imports have a unique batch hash and a supplier/document/date/type identity. Reuploading a renamed file skips identical documents. Reusing a document identity with different content is rejected for review. PostgreSQL advisory transaction locks serialize same-supplier imports across workers. Header totals must reconcile to line totals; credit-note signs are normalized. Product-level discounts must be allocated to their product lines. Unallocated discount lines are rejected, not converted into misleading COGS.

Realized purchases and freight include invoices and credit notes only. Proformas, supplier orders and pricelists provide cost evidence without double-counting financial purchases. Multiple invoices carrying the same supplier order ID count as one purchase order. A missing shipping charge is unknown, not automatically free shipping. Logistics retain INBOUND, DIRECT_SUPPLIER, RETURN and OTHER categories, monthly trend and ratios. Threshold simulations use existing invoiced orders and procurement freight; the top-up amount is extra purchasing, not profit or guaranteed savings. Cost-increase margin impact uses today's net catalog price held constant, not a historical realized margin comparison.

EUR is the only accepted supplier currency in this release. Unsupported currencies are rejected rather than mixed into EUR totals. Uploads are limited to 10 MB.

## API

All `/api/suppliers` endpoints require an administrator:

- GET `/summary?date_from=&date_to=`, `/products?as_of=`, `/unmatched`, `/performance?date_from=&date_to=`.
- GET `/catalog-search?q=` and `/mappings/{id}/cost-history`.
- POST `/imports` and multipart `/imports/json`; POST `/costs/manual` requires a verified mapping.
- PUT `/mappings/{id}/verify` and `/{supplier_id}/settings`.
- GET `/{supplier_id}/shipping-simulation?threshold=&date_from=&date_to=`.

Existing marketing revenue/spend calculations remain unchanged. Supplier profitability fields on `/api/dashboard/products` are only populated for administrators; `/api/dashboard/product-profitability` does not expose costs to non-admins. Audit retains its existing marketing product calculations.

## Validation

Install `backend/requirements-dev.txt` into a virtual environment. Migrate a separate PostgreSQL test database to head, then set `SUPPLIER_TEST_DATABASE_URL` to that database and run `python -m pytest backend/tests -q`. Integration tests use rollback isolation. Never point this variable at production.

Run `python -m compileall -q backend/app backend/alembic backend/tests`, frontend `npm run typecheck` and `npm run build`. Run `node frontend/tests/suppliers-smoke.cjs` against local Vite for desktop/mobile fixture-isolated workflow checks. Playwright must be available; set `PLAYWRIGHT_MODULE` to its package directory if it is not installed locally. `SUPPLIER_PREVIEW_URL` and `PLAYWRIGHT_CHANNEL` can override the default localhost:5175 and Chrome. Screenshots are generated under ignored `test-results`.

## Next Phase: Gmail And Supplier Adapters

`SupplierParser` remains the shared normalization interface. `NormalizedJsonParser` is unchanged; `MegapapParser` now accepts the audited MEGAPAP text-PDF order layout and equivalent HTML product tables. These are supplier orders, not fiscal invoices, regardless of filename. Unsupported/scanned layouts remain pending review, with no guessed costs. XLS/XLSX, supplier XML feeds and other suppliers are outside this phase.

Additive migration `0009_supplier_gmail` creates a receipt/review table only, preserving the existing supplier financial tables. Admin GET `/gmail`, POST `/gmail/sync`, PUT `/gmail/{source_id}/review` stage, inspect and accept/reject receipts. Gmail GET calls use a dedicated verified `gmail.readonly` token for `info@inde.gr` only; the sole network POST is OAuth token refresh. Completed messages are checkpointed on bounded reads. The database retains hashes/immutable IDs and normalized financial fields, not full email bodies, customer addresses or raw PDF binaries. Acceptance and financial import commit together. File/body and semantic hashes deduplicate forwards/renames; immutable financial identity rejects changed amounts. Pending documents must be explicitly confirmed as supplier-order evidence with freight net/VAT; then the existing historical-cost/import/mapping services are reused. Unmatched lines never assign fuzzy COGS. See [Gmail setup](supplier-gmail-setup.md) before enabling the default-disabled integration.
