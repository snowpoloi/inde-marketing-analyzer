# Provider invoice detail through AADE

The AADE connector remains GET-only. The worker uses the `downloadingInvoiceUrl`
already received from authenticated AADE responses and requests its `/myDATA`
representation. This is the provider download mechanism documented by AADE:
https://www.aade.gr/ekdosi-v1012

- All expense suppliers are eligible; a registered XML feed is not required to
  retrieve lines. A supplier/catalog identity is still required to accept costs.
- Only full documents addressed to the configured INDE AFM qualify. Book/VAT
  summaries, cancelled documents and disabled AADE integrations are excluded.
- Three invoices per 45-second worker tick, one running instance, row-lock claims
  and five-minute recoverable leases keep network work out of HTTP page loads.
- HTTPS exact provider-origin allowlist, public DNS, TLS verification, same-origin
  redirects only, GET only, no AADE headers, no environment proxy credentials.
- Each response is bounded to 2 MiB/30 seconds and 1,000 lines, parsed without
  DTD/entities, and checked for one invoice, MARK/UID, issuer/recipient, date,
  type/series/number/currency, summary totals and reconciled line net/VAT amounts.
- Original AADE data and all financial columns remain unchanged. Verified detail
  is stored separately under `raw._provider_detail`, with a source fingerprint.
  Resync retains it only if original source and normalized fields are unchanged.
  Source changes or cancellations cannot publish an in-flight stale response.
- Transient failures retry with hourly backoff, at most four attempts. Unsupported
  origins or non-verifiable documents remain unavailable, with a sanitized reason.
  New origins require a reviewed allowlist addition, not arbitrary URL access.
- AADE ledger and supplier cost previews consume verified lines only. Private
  download URLs are never returned in report fields, reasons or log messages.
- No cost records or product mappings are accepted automatically. Missing units,
  pack conversions, uncertain matches and fiscal adjustments retain review guards.
  Provider prices are not substituted for fiscal totals or inferred from summaries.

Statuses: `pending`, `running`, `retry`, `verified`, `unavailable`, `no_link`.
The worker backfills existing eligible invoices as well as newly synchronized ones.
Internal targeted diagnostics can pass `document_ids` to the same bounded job;
there is no public URL-fetch endpoint or AADE write capability.
