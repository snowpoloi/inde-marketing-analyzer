# Google Ads search terms, products, asset groups and Merchant Center issues

Four read-only dashboard endpoints, fed by new reports in the daily sync:

| Endpoint | Source | Table (migration) |
| --- | --- | --- |
| `GET /api/dashboard/google-search-terms` | Google Ads `search_term_view` (Search, Shopping) and `campaign_search_term_view` (Performance Max) | `google_ads_search_term_daily_metrics` (0020) |
| `GET /api/dashboard/google-products` | Google Ads `shopping_performance_view` (Shopping, Performance Max) | `google_ads_product_daily_metrics` (0021) |
| `GET /api/dashboard/google-asset-groups` | Google Ads `asset_group` (Performance Max) | `google_ads_asset_group_daily_metrics` (0022) |
| `GET /api/dashboard/merchant-issues` | Merchant API `products.list` (product status) | `merchant_product_statuses`, `merchant_product_issues` (0023) |

All are `GET` routes guarded by `get_current_user`, like the other dashboard routes, so the read-only `X-ADVESTIQ-Key` can read them. The body is `{"data": {...}}`. Ratios are `null` when their denominator is 0. Money is in the account currency, rounded to cents.

Conversions and conversion value are what Google Ads reports, not OpenCart orders.

## Sync

| Sync | Google Ads detail reports | Merchant statuses |
| --- | --- | --- |
| Daily 04:00 (`scheduled`, yesterday) | yes | yes |
| Manual (`POST /api/sync/run`) | yes, for its window | yes |
| Backfill (history jobs) | yes, for its window | no: the snapshot is today's state |
| Intraday (every 2 hours) | no | no |

- **Google Ads.** After the campaign report (unchanged), the sync reads:
  - search terms: per day, the 500 costliest Search and Shopping rows (per ad group and match type) and the 500 costliest Performance Max rows (per campaign). Two queries per day.
  - products: per day, the 2,000 costliest product + campaign rows. One query per day.
  - asset groups: every asset group with results in the window. One query.
- **Replace, never add.** Each report replaces every stored day of the synced window, so re-runs never duplicate rows and a day that now has fewer rows loses its stale ones.
- **Partial failures.** The campaign report decides the run's status. If a detail report fails, the run stays `success` and its error names the report (`Google Ads products report failed: …`). The meta has `google_ads_<report>_error`, and that table keeps its old rows for those days. On success the meta has `google_ads_search_terms_rows`, `google_ads_products_rows` and `google_ads_asset_groups_rows`. `google_ads_api_requests` counts the `search_stream` calls.
- **Why not intraday.** Same-day search terms and products are incomplete and their conversions arrive later. They would add 4 queries every two hours and are not needed to see that ads run. The 04:00 run reads the whole of yesterday.
- **Merchant.** After the product metrics (unchanged), scheduled and manual runs read every product's status with `products.list` (1,000 products per page) and replace the snapshot. A failed read keeps the previous snapshot: the run stays `success`, its error starts with `Merchant product statuses failed`, and the meta has `merchant_statuses_error`. On success the meta has `merchant_status_products`, `merchant_status_rows` and `merchant_issue_rows`. `merchant_api_requests` counts the HTTP requests. With a CSV export (`csv_url`, no OAuth) there are no statuses, and the meta says so.

## `GET /api/dashboard/google-search-terms`

Parameters: `date_from`, `date_to` (`YYYY-MM-DD`, default: the last 30 days up to today; `date_from` after `date_to` returns 400), `campaign` (campaign ID or exact campaign name, any case), `limit` (1–1000, default 100), `no_conversions` (`true`: only terms with cost and no conversions).

| Field | Meaning |
| --- | --- |
| `days_with_data`, `missing_days` | Days of the window with and without stored terms |
| `stored_rows_per_day` | `{"search_and_shopping": 500, "performance_max": 500}` |
| `totals` | `terms`, `impressions`, `clicks`, `cost`, `conversions`, `conversion_value`, `ctr`, `cpc`, `cost_per_conversion`, `conversion_value_per_cost`, `no_conversion_terms`, `no_conversion_cost` |
| `campaign_cost` | Campaign-level cost of the Search, Shopping and Performance Max campaigns on the days with data (only the `campaign` filter's campaign when set), or `null` |
| `cost_coverage` | `totals.cost / campaign_cost`: the share of the spend the stored terms explain |
| `terms[]` | Per search term over the window, costliest first, top `limit`: `search_term`, `days`, `match_types`, `statuses`, `campaign_types`, the metrics of `totals`, `no_conversions`, and `campaigns[]` (`campaign_id`, `campaign_name`, `campaign_type`, metrics, `no_conversions`) |
| `by_campaign[]` | Per campaign: `campaign_id`, `campaign_name`, `campaign_type`, `terms`, `no_conversion_cost`, metrics, `campaign_cost`, `cost_coverage` |
| `note` | How the rows were stored |

- `no_conversions` is `true` when the cost is above 0 and Google Ads counted no conversion. At term level it looks at all campaigns together; `by_campaign[].no_conversion_cost` adds up, per campaign, the terms without a conversion in that campaign.
- `ctr` is clicks / impressions × 100 (percent). `cpc` is cost / clicks. `conversion_value_per_cost` is conversion value / cost (Google's ROAS, not OpenCart's).
- `match_types`: `EXACT`, `PHRASE`, `BROAD`, `NEAR_EXACT`, `NEAR_PHRASE`, or `PERFORMANCE_MAX` for Performance Max terms.
- `statuses` (Search and Shopping only): `ADDED` (the term is a keyword), `EXCLUDED` (it is a negative keyword), `ADDED_EXCLUDED`, `NONE`. A term with cost, no conversions and status `NONE` is a candidate negative keyword.

## `GET /api/dashboard/google-products`

Parameters: `date_from`, `date_to`, `limit` (1–1000, default 100), `no_conversions`.

| Field | Meaning |
| --- | --- |
| `days_with_data`, `missing_days`, `stored_rows_per_day` (2000) | As above |
| `totals` | `products`, metrics as above, `no_conversion_products`, `no_conversion_cost` |
| `campaign_cost`, `cost_coverage` | Shopping and Performance Max campaign cost on the days with data, and the stored share |
| `catalog_match` | `products`, `matched`, `match_rate`, `matched_by` (`{"sku": n, "product_id": n, "model": n}`), `cost`, `matched_cost`, `cost_match_rate` |
| `products[]` | Per Google item ID, costliest first: `item_id`, `title`, `brand`, `custom_labels` (`{"custom_label_0": "…"}`, empty labels left out), `days`, `campaign_types`, metrics, `no_conversions`, `campaigns[]`, `catalog` |
| `products[].catalog` | The OpenCart catalog product, or `null`: `matched_by`, `sku`, `product_id`, `model`, `name`, `brand`, `category`, `price`, `quantity`, `status`, `link` |
| `by_campaign[]` | Per campaign: `products`, metrics, `campaign_cost`, `cost_coverage` |

Title, brand and labels are the latest stored ones. Item IDs are matched to the catalog by SKU first, then `product_id`, then model, ignoring case (Google Ads can report item IDs in lower case). Product rows count products shown in ads, so their cost does not add up to campaign cost.

## `GET /api/dashboard/google-asset-groups`

Parameters: `date_from`, `date_to`.

| Field | Meaning |
| --- | --- |
| `asset_groups[]` | Per asset group, costliest first: `asset_group_id`, `asset_group_name`, `asset_group_status` (latest), `campaign_id`, `campaign_name`, `first_date`, `last_date`, `days`, metrics |
| `daily[]` | Per day and asset group: `date`, `asset_group_id`, metrics |
| `totals` | `asset_groups` + metrics |
| `campaign_cost`, `cost_coverage` | Performance Max campaign cost on the days with data, and the share in asset groups |

## `GET /api/dashboard/merchant-issues`

The latest snapshot; no date window. Parameters: `severity` (`DISAPPROVED`, `DEMOTED` or `NOT_IMPACTED`: which issues make a product "affected"; default `DISAPPROVED` and `DEMOTED`), `reporting_context` (e.g. `SHOPPING_ADS`, `FREE_LISTINGS`), `limit` (affected products, 1–5000, default 500).

| Field | Meaning |
| --- | --- |
| `synced_at` | Time of the snapshot (sync time zone), or `null` before the first status sync |
| `products` | Products in the snapshot |
| `status_counts[]` | Per destination: `reporting_context`, `approved`, `pending`, `disapproved`, `partly_disapproved` (approved in some countries only), `unknown`, `total` |
| `severity_counts` | Products with at least one issue of each severity |
| `issue_counts[]` | Per issue: `code`, `severity`, `attribute`, `description`, `reporting_contexts`, `products`, `new_products`. Worst severity first, then most products. |
| `new_issue_rows` | Issues first seen in the latest snapshot |
| `affected_product_count`, `affected_products[]` | Products with an issue of `affected_severities` (disapproved first): `offer_id`, `feed_label`, `content_language`, `title`, `disapproved_destinations[]` (`reporting_context`, `status`, `status_since`), `issues[]` (`code`, `severity`, `attribute`, `reporting_context`, `description`, `detail`, `documentation`, `resolution`, `applicable_countries`, `first_seen_at`, `is_new`). With the `DISAPPROVED` severity, a product disapproved for a destination without an item-level issue is listed with `issues: []`. |

`status_since` and `first_seen_at` carry over between snapshots while the status or issue stays the same. In the very first snapshot every issue is new.

## API use

| Run | Google Ads `search_stream` calls | Merchant API requests |
| --- | --- | --- |
| Daily 04:00, one day | +4 (2 search terms, 1 products, 1 asset groups) on top of the campaign query | +1 per 1,000 products |
| Manual or backfill, N days | +3 × N + 1 | Manual: +1 per 1,000 products; backfill: none |
| Intraday | none | none |

Each `search_stream` call counts as one operation of the Google Ads daily quota (15,000 with Basic access), whatever the number of rows. A full two-year history backfill adds about 2,200 calls, spread over its 14-day jobs.

## What the APIs do not expose

- **Hidden search terms.** Google leaves out terms with too few searches, so stored terms never explain all the cost. `cost_coverage` shows how much they explain.
- **Performance Max search terms** come per campaign only: no asset group, no keyword, no keyword status. Their match type is always `PERFORMANCE_MAX`. Adding keyword fields to the query would drop the Performance Max rows. `campaign_search_term_view` needs Google Ads API v21 or later. The pinned `google-ads<30` library (29.2.0 when this was written) defaults to v23.
- **Product cost** covers products shown in ads. Spend on ads that show no product (for example some Performance Max video or display ads) is in the campaign cost but in no product row.
- **Placements.** Performance Max placements (`performance_max_placement_view`) only have impressions, so they are not stored.
- **No read-only OAuth scope.** Google Ads (`adwords`) and the Merchant API (`content`) have no read-only scope. The code only runs Google Ads search queries, Merchant `products.list` and Merchant report searches, and never calls a mutate or insert method.
