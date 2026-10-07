# Supplier Catalog

The existing Products page combines OpenCart order lines and the store's configured
OpenCart product feed (`product_feed_url`). Supplier catalog is a separate,
administrator-only XML catalog, including supplier products not listed in the shop.
It does not modify OpenCart products, orders, AADE documents, supplier costs or Gmail.

## Settings And Synchronization

Settings > Supplier XML feeds accepts a private URL, code, name, automatic-sync
toggle and refresh interval (6-168 hours, default 24). Explicit adapters support
the audited MEGAPAP and Pakoworld XML formats. Select the registered supplier/AFM
to reuse its existing identity code; the feed code must agree with the AADE supplier
code, including identities discovered as `AADE_<AFM>`. More formats require an
explicit adapter; arbitrary XML must not be interpreted as either catalog.

URLs are encrypted using a domain-separated key derived from the existing
application SECRET_KEY, never returned by the API or placed in sync errors.
Retain this key and database backups together; changing it requires resaving URLs.
An empty URL while editing preserves the stored value. Only HTTPS supplier hosts
are allowed, including redirects. No feed URL or token is seeded or committed.

The worker claims one feed every 45 seconds. Manual sync queues work and returns
immediately; automatic sync observes the configured interval. A 30-minute lease
recovers interrupted work. Requests are GET-only, downloads are limited to 50 MB
for MEGAPAP and 75 MB for Pakoworld (the audited feed is approximately 54 MiB)
and 120 seconds, product count to 20,000, and XML DTDs/entities are rejected.
A failed/empty/duplicate-model snapshot retains the complete previous catalog.
The catalog is atomically replaced via bounded PostgreSQL upserts. Missing products
are marked not-current rather than deleted. Stale data retains its last successful
timestamp; an error is shown until the next successful sync.

## Identity And Prices

Supplier model (including leading zeros), SKU and EAN remain separate identifiers.
An indexed-in-memory comparison to shop SKU/model/EAN/UPC/MPN links only a single
exact candidate. Conflicting identifiers or multiple candidates remain ambiguous;
names do not establish financial mappings. Pakoworld has no separate SKU: its
model also checks the shop SKU, with EAN conflicts still requiring review.
MEGAPAP matching is unchanged. Links are refreshed with each XML sync.
The AADE cost review establishes verified SupplierProductMap links through these
exact XML identifiers; catalog synchronization alone does not approve costs.

XML wholesale prices are supplier list prices, **not invoiced purchase costs**.
Retail prices are VAT-inclusive; wholesale prices are VAT-exclusive as labeled by
MEGAPAP. No price or stock overwrites the shop catalog. Filters and descriptions
retain supplier provenance; AI does not generate any values. Supplier volume and
weight fields are raw values until units and business meanings are confirmed.
Pakoworld's `net_price`, `stock_price` and `has_net_price` are retained as supplier
fields, but their tax basis is not confirmed; they do not populate the tax-labelled
XML wholesale column or purchase costs. `retail_price_with_vat` remains gross.
Attributes, categories, sale step, expected availability and component identifiers
are retained. Components are not exploded into purchase units. Pakoworld dimensions
and weights remain supplier raw data, not calculated shipping parcel dimensions.
Each adapter permits only its own HTTPS host for downloads, redirects and media.
Zero combined dimensions are unknown, not zero-size parcels. Product dimensions
must never automatically become packaging dimensions.

Migration 0011 adds two tables only. Reviewed AADE costs reuse the existing supplier
document, mapping and cost tables; no additional migration or Gmail evidence is needed.
## Price Comparison

The catalog shows the matched INDE feed price separately from XML wholesale and
retail list prices. AADE purchase cost is the latest verified, active EUR product
unit cost explicitly sourced as `aade_invoice`, linked through an invoice line
to a non-cancelled AADE expense invoice from the same supplier. A reconciled
Gmail/imported invoice is not by itself AADE cost evidence. Different unit costs
on the latest purchase date remain unresolved instead of choosing arbitrarily.

Gross profit per unit and gross margin use net sale price and net purchase cost.
Margin is `(net sale - net cost) / net sale * 100`, not markup on cost, and excludes
shipping, advertising and overhead. No XML or Gmail fallback is permitted. The
AADE cost ingestion/approval bridge is described below.

INDE catalog prices are VAT-inclusive, confirmed by the owner. Settings > Catalog
costs & packages stores the confirmed selling VAT rate; explicit per-product VAT
rates take precedence. Without that setting, the original explicit `price_net` /
`prices_include_vat` metadata rules still apply. Missing cost, unknown VAT basis,
foreign currency and zero sale price never produce a fabricated margin percentage.

## Reviewed AADE Costs

Settings > Supplier identities stores a supplier code, official company name and
unique nine-digit AFM. Codes must agree with the supplier XML feed. The registered
name fills missing issuer names on expense ledger rows without overwriting myDATA.
AFM changes are blocked after an AADE cost import. Identity changes are audited.

Suppliers & COGS > AADE costs lists locally stored invoices for a registered AFM
and selected period, 50 per page. It makes no AADE or Gmail network requests.
Review requires full expense invoices for goods (1.1/1.2/1.3), EUR, INDE recipient
AFM, MARK/number, non-future date, explicit quantities, piece units, net/VAT values,
unique exact XML identifiers and an INDE product. Descriptions alone, absent fields,
special fee/adjustment rows, credits, service invoices and delivery notes cannot
be accepted. All line amounts must reconcile to fiscal net/VAT/gross totals.

The administrator confirms products and one purchase piece per INDE sales unit.
Acceptance rechecks the preview fingerprint under locks and writes historical
`aade_invoice` costs. Net unit cost = invoiced net line amount / quantity (four
decimal places). Freight stays separate. No sale prices, OpenCart products or
AADE data are modified. MARK deduplication applies across source endpoints and
legacy invoice imports are blocked for reconciliation instead of counted twice.

Cancelled, conflicting or subsequently changed fiscal sources invalidate their
accepted costs and purchase/freight aggregates. The latest invalid evidence can
leave the catalog cost blank; this does not silently fall back to an XML list price.
This is verified invoice unit costing, not a stock/FIFO or full net-profit engine.

## Automatic Cost Updates

The administrator can enable automatic AADE purchase costs in Settings. The
background worker processes at most one stored invoice every 45 seconds. It uses
the same fiscal, amount, mapping, cancellation and duplicate guards as manual
acceptance, and records the authorizing administrator plus an automated audit
flag. No external fiscal writes or OpenCart selling-price changes are made.
Invoices without unit codes require a saved supplier-specific 1:1 purchase/sales
unit confirmation. Explicit non-piece units are never overridden. Blocked invoices
remain for review and retry after six hours; XML list prices never become costs.
Imported invoices are not duplicated. Corrected/cancelled source evidence remains
invalid until separately reconciled rather than silently replacing history.

## Per-Package Dimensions

MEGAPAP combines labeled `BOX A`, `BOX B`, etc. in each `comb_*_cm` field. The
parser preserves source text and joins axes by box label (not source position).
Every declared package is displayed, including unknown dimensions. Single numeric
dimensions apply only to a declared single package. Totals require all declared
packages to have usable dimensions; combined volume is never divided evenly.
Volume = width * length * height / 1,000,000 m3. Volumetric weight uses the saved
carrier divisor in cm3/kg (initial editable reference: 5,000), shown in the table.
This is not measured weight or a freight price. Pakoworld does not currently
provide these labeled package dimensions; product dimensions are not substituted.
