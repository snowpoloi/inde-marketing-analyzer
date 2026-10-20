# Business Review

Admin-only `#business-review` compares two periods using persisted data. No ads,
budgets, shop products or bank transactions are changed by this feature.

## Stored Data

- Existing daily Ads, GA4, Merchant, Search Console, OpenCart and AADE tables remain
  the source of truth. Backfill uses the same importers and credentials.
- `review_jobs` stores idempotent provider/date windows, attempts, outcomes and gaps.
  The worker processes one window at a time, once per minute, deferring while a
  normal sync is active. A separate provider lock prevents overlapping imports
  across manual, scheduled and historical syncs.
- `review_events` stores API change events and supporting email/manual/export
  evidence. Every event keeps its evidence type and optional source link. Secrets
  are redacted; links with embedded credentials are rejected.
- `review_reports` stores immutable comparison snapshots. Live reports can change
  as orders are cancelled, conversions mature or cost evidence arrives.

The normal 04:00 sync also queues recent Google and Meta change history. Reports
do not auto-refresh; only the visible historical job list polls every 15 seconds.
Pause stops pending windows, not an already running provider request. Retry/resume
requeues failed, skipped and paused windows; unavailable retention gaps remain.

## Acquisition Limits

Google's ChangeEvent API only exposes the recent 30-day window and a maximum of
10,000 events per query. The collector conservatively requests 28 days, in daily
slices, and fails on a full 10,000-event slice instead of silently truncating it.
Older Google history requires an account Change History export. Campaign IDs are
used for comparison so renames do not create artificial gains or losses.

Meta changes use the read-only ad-account `/activities` endpoint, following
cursors. Returned events are evidence, not proof that all historical events were
exposed. Missing permissions and pagination failures are visible job failures.

TikTok metrics use the existing reporting connector. TikTok change history needs
an export. Shoply segmentation/change history needs its logs or exports; email
claims are labelled as reports, not API-confirmed changes. No new Gmail ingestion
or external AI processing is enabled. Evidence CSV accepts:

```csv
source,occurred_at,title,detail,actor,object_id,reference_url,evidence_type
shoply,2026-10-01T12:00:00+03:00,Reported update,Supporting details,,,,email
```

CSV is UTF-8, at most 5 MB / 10,000 rows. Dates without a timezone are interpreted
as Athens time. Evidence type is manual/email/export; uploaded data cannot
impersonate API verification. Native platform exports need normalization into
this schema, preserving their source, actual change time and actor.

Banks retain their existing statement-import workflow. Merchant performance
history is not an approval/disapproval history. Product state before snapshots
were collected cannot be reconstructed from a current feed.

## Financial And Causal Boundaries

- Order totals include tax/shipping and configured sale statuses, not necessarily
  paid or fulfilled orders. Product-line comparisons use recorded price * quantity.
- Ads platforms can attribute the same purchase. Their revenues must not be added.
  Google conversions can include goals other than purchases.
- AADE totals use non-cancelled full EUR documents and subtract credit notes.
  Book/VAT summaries are excluded because they overlap full documents. Book-only
  data is unknown, not zero fiscal income/expense.
- Bank inflows/outflows include transfers and are not additional sales/profit.
- Optional invoice COGS shows only fully covered products, separately per period,
  using the existing later-invoice estimate policy. This is not business net profit.
- Successful sync coverage proves a range was requested, not that a remote source
  exposed complete data. Missing data yields nulls; partial coverage is flagged.
- Findings decompose value, order count, average order, spend and attributed ROAS.
  Product/category contributions and low-ROAS warnings are observations, not
  causal attribution or automatic budget recommendations.

## Deployment And Verification

Migration `0012_business_review` adds three tables without modifying existing
financial records. Both backend and worker must deploy the same commit. No new
credentials or external permissions are required.

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
# Set SUPPLIER_TEST_DATABASE_URL to an isolated database migrated to head.
python -m pytest backend/tests -q
```

Tests cover source gaps versus genuine zero activity, campaign renames, Meta link
clicks, credit notes/currency/cancellations, Athens event boundaries, idempotency,
queue behavior, provider locks, immutable reports, admin authorization, atomic
CSV validation and secret redaction.

Sources:
- https://developers.google.com/google-ads/api/docs/change-event
- https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py
- https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adactivity.py
- https://www.aade.gr/sites/default/files/2025-12/myDATA%20API%20Documentation%20v2.0.0_official_erp.pdf
