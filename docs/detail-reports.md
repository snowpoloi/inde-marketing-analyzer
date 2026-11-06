# Detail reports, intraday sync and data freshness

Four read-only dashboard endpoints (GA4 funnel, GA4 landing pages, Meta per ad, sync freshness), a change to the GA4 sync, and same-day syncs of today.

## GA4 sync

- **Re-sync of the last 3 days.** Every GA4 sync (scheduled, manual or backfill) reads at least the 3 days that end on its `date_to`, and replaces every stored row of those days in `ga4_daily_metrics`, `ga4_funnel_daily_metrics` and `ga4_landing_page_daily_metrics`. The 04:00 run for yesterday (D) reads D-2 to D. GA4 finishes source attribution 24–48 hours late, so a single early read left some days' purchases under source `(not set)`. The run's `date_from` shows the widened window.
- **Three reports per run.** Channel metrics (as before), the purchase funnel and the landing pages. Each report is read page by page (10,000 rows per page). Before, a long manual range was silently cut at GA4's default limit of 10,000 rows.
- **Partial failures.** Channel metrics decide the run's status. If the funnel or the landing-page report fails, the run stays `success`, its error names the failed report (`GA4 landing pages report failed: …`), the meta has `ga4_funnel_error` or `ga4_landing_page_error`, and that table keeps its old rows for those days.
- **Quota.** Each run stores in its meta `ga4_quota`: the requests made, the tokens they used and the tokens left for the day and hour, as GA4 reports them.

## Endpoints

All three are `GET`, use the same login as the other dashboard routes, and accept `date_from` and `date_to` (`YYYY-MM-DD`, default: the last 30 days up to today). A `date_from` after `date_to` returns 400. The body is `{"data": {...}}`.

Common fields: `date_from`, `date_to`, `days_with_data` (days of the window with stored rows) and `missing_days` (days without; today and yesterday can be missing before the 04:00 sync). Ratios are `null` when their denominator is 0, so "no data" never reads as 0.

### `GET /api/dashboard/funnel`

Purchase-funnel events from GA4 per day, device category and default channel group.

| Field | Meaning |
| --- | --- |
| `steps` | Funnel order: `session_start`, `view_item`, `add_to_cart`, `view_cart`, `begin_checkout`, `add_shipping_info`, `add_payment_info`, `place_an_order`, `purchase` |
| `totals.event_count` | `{step: count}` for the window. Every step is present (0 when GA4 had none). |
| `totals.users` | `{step: users}`: GA4 `totalUsers` per day, device and channel row, added up (see `users_note`). |
| `totals.user_rate_from_start` | `{step: users[step] / users.session_start}` for every step after the first |
| `totals.user_rate_from_previous` | `{step: users[step] / users[previous step]}` |
| `by_device[]` | `device_category` + the same four objects. Sorted by `session_start` users. |
| `by_channel[]` | `channel_group` + the same four objects. Sorted the same way. |
| `daily[]` | `date` + `event_count` and `users` |
| `users_note` | Users are not de-duplicated across days, devices or channels, so user rates are approximate. `event_count` adds up exactly. |

### `GET /api/dashboard/landing-pages`

The top landing pages per day and default channel group, by sessions. Extra parameters: `limit` (1–1000, default 100) and `channel_group` (an exact GA4 default channel group, e.g. `Paid Social`).

The sync reads every landing page of the day and removes click IDs and sensitive values from the query string before it ranks them: `fbclid`, `gclid`, `gbraid`, `wbraid`, `dclid`, `gclsrc`, `gad_source`, `gad_campaignid`, `srsltid`, `msclkid`, `ttclid`, `twclid`, `li_fat_id`, `yclid`, `epik`, `igshid`, `rdt_cid`, `irclickid`, `mc_eid`, `_gl`, `_ga`, `_kx`, `sccid`, `email`, `e-mail`, `token`, `code`, `key`, `password`, `hash`. A click ID is unique per visit, so without this every paid click would be its own one-session page and paid traffic would never reach the top 200. All metrics are per session, so merged rows add up exactly. Other parameters (`utm_*`, `route`, `product_id`, `page`…) are kept. The 200 largest rows per day are stored; a stored page is cut at 1,000 characters.

| Field | Meaning |
| --- | --- |
| `rows[]` | Per landing page + channel group, summed over the window, top `limit` by sessions: `landing_page`, `channel_group`, `days` (days it was in the day's top 200), `sessions`, `engaged_sessions`, `add_to_carts`, `purchases`, `purchase_revenue`, `engagement_rate`, `add_to_carts_per_session`, `purchases_per_session`, `revenue_per_session` |
| `pages[]` | The same metrics per landing page across channels, with `channel_groups` (list) |
| `totals` | The same metrics for all stored rows of the window |
| `ga4_sessions` | All GA4 sessions of the days with landing-page data (from the channel report, same channel filter), or `null` |
| `session_coverage` | `totals.sessions / ga4_sessions`: the share of traffic the stored top rows cover |
| `stored_rows_per_day` | 200 |
| `channel_group` | The filter, or `null` |
| `note` | How the rows were stored |

`add_to_carts` and `purchases` are GA4 event counts (`addToCarts`, `ecommercePurchases`), so `add_to_carts_per_session` is not a share of sessions and can exceed 1.

### `GET /api/dashboard/meta-ads`

Meta results per ad, from the `meta_ads` rows already stored by the Meta sync (one row per ad and day).

| Field | Meaning |
| --- | --- |
| `ads[]` | Per ad, sorted by spend: `ad_id`, `ad_name`, `adset_id`, `adset_name`, `campaign_id`, `campaign_name` (latest names), `first_date`, `last_date`, `days`, `spend`, `impressions`, `link_clicks`, `landing_page_views`, `add_to_cart`, `initiate_checkout`, `purchases`, `purchase_value`, `ctr`, `cpc`, `cpm`, `roas`, `cost_per_purchase`, `reach_daily_max`, `reach_daily_sum`, `frequency_min`, `frequency_max` |
| `daily[]` | Per ad and day, sorted by date then spend: `date`, `ad_id`, `reach`, `frequency` (= impressions / reach), and the same metrics as `ads[]` |
| `totals` | The same metrics for all Meta rows of the window, including rows without an ad |
| `unassigned` | Meta rows without an `ad_id` (e.g. a campaign-level CSV import): `rows` + metrics, or `null` |
| `reach_note` | How reach is handled (below) |

Metrics: `ctr` = link clicks / impressions × 100 (percent), `cpc` = spend / link clicks, `cpm` = spend / impressions × 1000, `roas` = purchase value / spend, `cost_per_purchase` = spend / purchases. Purchases and their value are what Meta reports, not OpenCart orders.

Reach: Meta's daily reach counts unique people per day, so it cannot be added across days. Daily rows have the exact reach and frequency. Per-ad totals give bounds instead. The window's unique reach is at least `reach_daily_max` (the highest daily reach) and at most `reach_daily_sum`. So the window's frequency lies between `frequency_min` (impressions / `reach_daily_sum`, the average daily frequency) and `frequency_max` (impressions / `reach_daily_max`). For a one-day window both bounds are exact.

## Merchant category levels and custom labels

The Merchant API sync now also reads category levels 1–5 (Google product category and product type) and custom labels 0–4. Custom labels exist only in `product_performance_view` (`product_view` has no custom-label fields), so they come from there. Category levels come from both views, and `product_view` wins when product health is enabled. They are stored in each row's `raw`, so there is no migration. The audit `feed` rows (`GET /api/dashboard/audit` → `data.feed[]`) gain `category_levels`, `product_type_levels` and `custom_labels` (`{"custom_label_0": "…"}`, empty labels left out), from the latest day of the window. Rows synced before this change show empty values. The Audit page shows them as **Category** and **Custom labels** columns.

If a product's custom labels change during a day, Merchant returns two rows for it that day. Clicks and impressions per product are still summed as before.

## Intraday sync

The worker syncs **today** during the day, so same-day spend and orders are visible without a manual sync.

| Setting | Default | Meaning |
| --- | --- | --- |
| `SYNC_INTRADAY_HOURS` | `8,10,12,14,16,18,20,22` | Hours in `SYNC_TIMEZONE` (Europe/Athens). Empty or `off` turns the intraday sync off. |
| `SYNC_INTRADAY_PROVIDERS` | `google_ads,meta_ads,tiktok_ads,opencart,ga4` | Providers to sync. Empty or `off` turns it off. |

Both are set on the `backend` and `worker` services in `docker-compose.yaml` and `docker-compose.yml`. The worker runs the job; the backend shows the schedule in `GET /api/dashboard/freshness`. The compose files use `${VAR-default}` (no colon), so an empty value stays empty and really turns the job off.

- The 04:00 daily sync of yesterday for all providers is unchanged and re-reads yesterday in full.
- Intraday runs have `sync_type` `intraday`, so the Sync logs keep them apart.
- Window: today. GA4 combines it with the 3-day re-sync, so it reads today and the 2 days before.
- Disabled integrations are left out, so they add no skipped runs every two hours.
- The job runs with `max_instances=1, coalesce=True`. A provider whose previous run still holds its lock (e.g. a long manual sync) gets a `skipped` run with reason `provider_busy`.
- **Repeated runs are safe.** Ad rows are deleted and re-inserted per source and date. GA4 replaces its window. OpenCart upserts orders by `order_id` and replaces their products. The order change log now compares dates as moments, so a database in a non-UTC time zone no longer logs a false `date_added` change on every re-import.
- OpenCart intraday runs read orders only. The full product feed and the supplier XML refresh stay with the 04:00 sync.
- **Change history.** When `google_ads` or `meta_ads` is an intraday provider, each run also queues the recent change-history window (today and the 3 days before) again once its previous run has finished, so same-day account changes show up. This costs 5 small Google Ads queries (the account time zone, then one per day) and 1–3 Meta activity pages per run. Events are de-duplicated, so re-reading only adds new changes.

Extra API calls per day with the defaults (8 runs), on top of the 04:00 sync:

| Provider | Per intraday run | Extra per day |
| --- | --- | --- |
| Google Ads | 1 report query (`search_stream`), plus 5 change-history queries | about 8 + 40 |
| Meta | 1 insights page (up to 500 ad rows), plus 1–3 activity pages | about 8 + 8–24 |
| TikTok | 1 report page (up to 1,000 rows) | about 8 |
| OpenCart | 1 orders call to the shop's own endpoint (no product feed) | 8 |
| GA4 | 3 reports (channels, funnel, landing pages) over 3 days, about 1 page each | about 24, plus their tokens (see `ga4_quota` in each run) |

**Today's numbers are early and keep changing.** Google Ads can be up to about 3 hours behind, and its conversions arrive later. Meta and TikTok are usually within an hour or two. GA4 can take several hours to process a standard property, and its source attribution settles 24–48 hours later. All of them change until the day ends and after, as conversions are attributed. Use intraday numbers to see that ads are running and spending, not to judge results. The 04:00 sync replaces yesterday with fuller numbers.

## `GET /api/dashboard/freshness`

When each provider was last synced. No parameters. It is a `GET` dashboard route, so the read-only `X-ADVESTIQ-Key` can read it. It never returns error text or run meta, because those can contain API details.

| Field | Meaning |
| --- | --- |
| `now`, `today`, `timezone` | Server time and today's date in the sync time zone |
| `daily_sync_hour` | The hour of the daily sync of yesterday |
| `intraday` | `hours`, `providers` and `next_run_at` (ISO time of the next intraday run, or `null` when off) |
| `providers[]` | One row per provider: `provider`, `name`, `enabled` (`null` when not configured), `intraday`, `latest_run`, `last_success`, `today_synced_at` |
| `latest_run`, `last_success` | `status`, `sync_type`, `started_at`, `finished_at`, `date_from`, `date_to`, `records_processed`, `has_error` (true when the run stored an error message, e.g. a failed GA4 landing-page report), or `null` |
| `today_synced_at` | When the latest successful run whose window includes today finished, or `null` |

Times are ISO 8601 with the offset of the sync time zone.

## "Ενημέρωση σήμερα" on the ADVESTIQ page

The ADVESTIQ page (admins only) shows when today's data was last synced for each intraday provider, and the time of the next automatic run. Its **Ενημέρωση σήμερα** button runs today's sync for the enabled intraday providers through the existing `POST /api/sync/run` (a manual run, with the logged-in admin's session). The `X-ADVESTIQ-Key` stays blocked from `/api/sync`.
