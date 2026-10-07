# AADE catalog purchase costs

Supplier catalog exposes AADE costs with period and supplier selection. Imports
are admin-only, user initiated and bounded to five full invoices per request.
The browser processes requests sequentially and can stop after the in-flight
batch. Closing the dialog stops subsequent requests, not a committed import.

All existing invoice identity, cancellation, reconciliation, exact XML identifier,
mapping and duplicate guards apply. A blocked invoice is reported and not partly
imported. Delivery notes, credit notes and services do not set purchase unit costs.
Shipping is stored separately, excluded from product unit cost. XML prices and
Gmail prices are never substituted for invoice costs.

The caller explicitly confirms a 1:1 purchase-to-INDE sales unit relationship.
An additional confirmation can resolve only missing units, never explicit kg,
pack or other incompatible units. Original AADE data remains unchanged; reviewed
unit decisions and reviewer identity are recorded on the accepted evidence.
The confirmation participates in the preview fingerprint and is rechecked under
the existing import locks. No confirmation is silently remembered for another
supplier or period.

Catalog rows already consume latest accepted fiscal costs. Different unit costs
on the latest purchase date remain ambiguous, not chosen arbitrarily. Source
changes, cancellation and conflicting copies invalidate accepted evidence.
Sales prices, VAT assumptions and OpenCart data are not modified. Margins are
shown only when the existing net sales-price basis is known.
