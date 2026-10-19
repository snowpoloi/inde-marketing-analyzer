# AADE catalog purchase costs

Supplier catalog exposes AADE costs with period and supplier selection. Imports
are admin-only, user initiated and bounded to one full invoice per request,
so several costly invoice imports cannot exhaust a single proxy timeout.
The browser processes requests sequentially and can stop after the in-flight
batch. Closing the dialog stops subsequent requests, not a committed import.

All existing invoice identity, cancellation, reconciliation, exact XML identifier,
mapping and duplicate guards apply. Global fiscal failures block the invoice;
unmatched product lines remain pending while independently safe lines may be
accepted. Delivery notes, credit notes and services do not set purchase unit costs.
Shipping is stored separately, excluded from product unit cost. XML prices and
Gmail prices are never substituted for invoice costs.

The caller explicitly confirms one purchased unit equals one physical product piece;
catalog sale sets still multiply piece cost by `sell_step` / `minimum` separately.
An additional confirmation can resolve only missing units, never explicit kg,
pack or other incompatible units. Original AADE data remains unchanged; reviewed
unit decisions and reviewer identity are recorded on the accepted evidence.
The confirmation participates in the preview fingerprint and is rechecked under
the existing import locks. Unit confirmations never authorize another supplier.

Catalog rows already consume latest accepted fiscal costs. Different unit costs
on the latest purchase date remain ambiguous, not chosen arbitrarily. Source
changes, cancellation and conflicting copies invalidate accepted evidence.
Sales prices, VAT assumptions and OpenCart data are not modified. Margins are
shown only when the existing net sales-price basis is known.

Cost-source fingerprints normalize equivalent quantity encodings (`1`, `1.0000`)
and header amount scale. Other invoice-line fields, including product identifiers,
units, descriptions, amounts and fiscal flags, remain exact. Legacy fingerprints
remain usable when they match the current source exactly, or when the original
AADE payload still matches the saved fingerprint and verified provider detail is
identical after this normalization. No price, mapping or financial evidence is
rewritten to recover a formatting-only change.
Successful upgrades retain the previous fingerprint for audit and existing
invoice-only human confirmations; a changed fiscal source cannot reuse it.

The invoice list derives the cost status from validated stored evidence rather
than a stale worker label. A complete invoice whose source changes is checked
again by the bounded worker; real changes remain blocked and appear in Pending
Costings, including invoices with no remaining unmatched lines.

## Pending Costings

Supplier catalog > **Εκκρεμείς κοστολογήσεις** lists unresolved goods invoices in
the selected period, with a supplier filter and ten invoices per page. Duplicate
AADE endpoint copies are grouped by MARK, preferring full invoice detail. Each
product row shows its original code/title, quantity, net line value, calculated
invoice-unit price and blocking reasons. Invoice links open the stored detail in
a new tab. Summaries without product detail remain visibly blocked.

Expand a row, search/select an INDE product and explicitly confirm physical-piece
units. Confirmation accepts only that selected line, preserving the complete
reconciled invoice and leaving other lines available for later approval. Price,
quantity and VAT cannot be edited through this endpoint. Missing units may be
confirmed for the selected code/line only; explicit kg/pack units and missing
amounts or quantities cannot be bypassed. Repeated submissions are idempotent.

The optional future-invoice checkbox stores a verified mapping scoped to supplier
and normalized invoice code. Without a code, only invoice-line-specific approval
is allowed. A unique matching XML row can also receive the reviewed INDE link;
ambiguous XML candidates are not linked en masse. XML refresh preserves reviewed
links only while the supplier and INDE identifiers remain unchanged. Identifier
drift requires review. Reassigning a code already used by financial evidence is
blocked; an invoice-only exception does not rewrite historical cost records.

The mapping records reviewer/time, source digest, invoice MARK/line and identity
snapshots. Approval wakes the existing bounded AADE worker for historical partial
invoices, without enabling automatic costing if disabled. No migration, OpenCart
write, AADE network call or invented purchase price is introduced. Background
refreshes do not discard an open review form; stale confirmations fail safely.
