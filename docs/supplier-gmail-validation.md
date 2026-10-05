# MEGAPAP Gmail Phase Validation

Baseline: local HEAD was `7f6c591` on `main`, with a clean working tree before this phase. The existing Supplier/COGS module and historical-cost policy were retained. No supplier XML feeds or other supplier adapters were added.

## Financial Acceptance

The supplied real-data example is anonymized in `backend/tests/fixtures/megapap_acceptance.json`:

| Check | Verified result |
| --- | --- |
| Supplier internal code | `0212605`, retained as a secondary identifier |
| Supplier SKU / OpenCart model | `GP041-0025,4`, exact unique model matching |
| Net purchase unit cost | EUR 8.73 |
| Gross sale / VAT | EUR 15.90 / 24% |
| Net sale | EUR 12.8226 |
| Product gross profit | EUR 4.0926 |
| Product margin | 31.92% |
| 2026-08-15 sale | Uses 2026-07-01 cost 8.20 |
| 2026-09-15 sale | Uses 2026-09-01 cost 8.50 |
| 2026-10-02 sale | Uses same-day cost 8.73 |
| Sale before earliest evidence | Unknown COGS, never future evidence |
| Supplier freight / products | 4.90 / 85.68 = 5.72%, logistics only |

Ledger integration verifies that changing supplier logistics does not reduce Product Margin. Previously verified mappings remain first priority; numeric codes and fuzzy product names do not automatically assign MEGAPAP costs.

## Parser And Review

The audited PDF field structure was reproduced in a new, anonymous `megapap_order.pdf` and equivalent HTML fixture. The original customer PDF and audit sources were not committed. The parser was also exercised read-only on the original local audit sample; the known product/subtotal/freight/VAT/total reconciled.

The audited layout is a **supplier order**, even if named `Invoice-*.pdf`. Gmail intake stages it first. An administrator must explicitly confirm the evidence type and freight net/VAT before financial import. It provides historical cost evidence, not realized fiscal purchases. Unknown fiscal-invoice layouts, scans, invalid totals and unsupported charges stay in review with no financial writes. HTML body tables are supported; unstructured plain text needs manual review. No OCR or XLS/XML parser was added.

Accepted freight uses the existing shipping table, not product COGS. Unmatched products expose supplier/document/SKU/code/description/cost/candidates/reason. Verified mappings persist and are reused on subsequent documents.

## Safety And Deduplication

- Only `info@inde.gr` is allowed. Gmail network requests are GET-only; OAuth refresh is the only connector POST. Broader tokens and mismatched OAuth clients/accounts are rejected before message access.
- Immutable message/part/attachment identifiers and SHA-256 body/file hashes prevent repeated downloads/imports. Canonical document hashes deduplicate equivalent PDF/HTML and renamed/forwarded copies.
- Changed amounts for an existing financial identity are rejected for review. Concurrent receipt creation and concurrent acceptance were tested with independent PostgreSQL sessions; they commit once.
- Receipt acceptance and existing financial import commit atomically. Rejected/unsupported/pending items never produce cost rows. Completed messages checkpoint independently during paginated reads.
- OAuth tokens are absent from fixtures/Git/API output; tokeninfo URL logging is suppressed. Only normalized financial fields and hashes are stored, not full customer email/PDF content.

## Verification Run

- 68 backend tests passed against an isolated PostgreSQL 17 database, including financial acceptance, parser, Gmail scope/mailbox/method safety, API authorization, duplicate/conflict/review and concurrency tests.
- Migration `0009 -> 0008 -> 0009` passed on that isolated database, preserving an existing supplier invoice. Model-column/index checks passed. No production downgrade was performed.
- Python compileall, frontend typecheck and production build passed.
- Playwright supplier/import/mapping/history/logistics/Gmail review workflows passed at desktop 1440px and mobile 390px. Screenshots checked for layout and page overflow; anonymous PDF rendered and inspected.
- One existing Starlette/httpx TestClient deprecation warning remains; tests pass.

## Activation Boundary

The integration is disabled by default. Server Gmail credentials have not been configured and **no live server ingestion has been verified**. The Codex Gmail connection is not reused. Follow [the separate Google OAuth/Coolify setup](supplier-gmail-setup.md). This phase stops at MEGAPAP; it does not start background scheduling, other suppliers or XML feeds.
