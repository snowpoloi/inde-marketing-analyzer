# Supplier Catalog

The existing Products page combines OpenCart order lines and the store's configured
OpenCart product feed (`product_feed_url`). Supplier catalog is a separate,
administrator-only XML catalog, including supplier products not listed in the shop.
It does not modify OpenCart products, orders, AADE documents, supplier costs or Gmail.

## Settings And Synchronization

Settings > Supplier XML feeds accepts a private URL, code, name, automatic-sync
toggle and refresh interval (6-168 hours, default 24). The first adapter supports
the audited MEGAPAP XML format only. More supplier formats require an explicit
adapter; an arbitrary XML must not be interpreted as a MEGAPAP catalog.

URLs are encrypted using a domain-separated key derived from the existing
application SECRET_KEY, never returned by the API or placed in sync errors.
Retain this key and database backups together; changing it requires resaving URLs.
An empty URL while editing preserves the stored value. Only HTTPS supplier hosts
are allowed, including redirects. No feed URL or token is seeded or committed.

The worker claims one feed every 45 seconds. Manual sync queues work and returns
immediately; automatic sync observes the configured interval. A 30-minute lease
recovers interrupted work. Requests are GET-only, downloads are limited to 50 MB
and 120 seconds, product count to 20,000, and XML DTDs/entities are rejected.
A failed/empty/duplicate-model snapshot retains the complete previous catalog.
The catalog is atomically replaced via bounded PostgreSQL upserts. Missing products
are marked not-current rather than deleted. Stale data retains its last successful
timestamp; an error is shown until the next successful sync.

## Identity And Prices

Supplier model (including leading zeros), SKU and EAN remain separate identifiers.
An indexed-in-memory comparison to shop SKU/model/EAN/UPC/MPN links only a single
exact candidate. Conflicting identifiers or multiple candidates remain ambiguous;
names do not establish financial mappings. Links are refreshed with each XML sync.
The catalog does not yet establish SupplierProductMap/AADE cost links.

XML wholesale prices are supplier list prices, **not invoiced purchase costs**.
Retail prices are VAT-inclusive; wholesale prices are VAT-exclusive as labeled by
MEGAPAP. No price or stock overwrites the shop catalog. Filters and descriptions
retain supplier provenance; AI does not generate any values. Supplier volume and
weight fields are raw values until units and business meanings are confirmed.
Zero combined dimensions are unknown, not zero-size parcels. Product dimensions
must never automatically become packaging dimensions.

Migration 0011 adds two tables only. The next financial phase will bridge supplier
codes in full AADE expense invoice lines to this catalog, validate quantities/units,
reconcile amounts and retain historical net invoice costs without Gmail evidence.
It is not part of this catalog release.
