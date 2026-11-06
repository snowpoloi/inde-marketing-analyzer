# ADVESTIQ access

ADVESTIQ is the read-only ad-agency assistant that runs in Claude Code on the owner's computer. It reads the Analyzer every morning, writes a brief and proposes changes. It never changes anything in the ad accounts or in the Analyzer.

## What this change adds

| Change | Why |
| --- | --- |
| `X-ADVESTIQ-Key` header (`app/api/deps.py`) | Lets ADVESTIQ read the API without a 24-hour login token. The key can only make GET requests, plus the three writes listed under [What the key may write](#what-the-key-may-write). It can never reach `/api/settings/integrations`, `/api/sync/*` or `/api/auth/*`. |
| Masked secrets in `GET /api/settings/integrations` | Tokens, secrets, passwords, API keys and service-account JSON are returned as `••••` + last 4 characters. On save, an unchanged masked value keeps the stored secret, so the Settings page works as before. |
| `GET /api/business-review/events?date_from&date_to&limit` | Date filter on the change history. Without parameters it behaves as before (latest 1,000). |
| `GET /api/business-review/events/summary?date_from&date_to` | Changes per Athens day. Groups of 50+ identical changes (e.g. the nightly feed upload) are folded into one row, so manual changes stay visible. |
| `advestiq_reports` table, `/api/advestiq/reports` and the **ADVESTIQ** page | ADVESTIQ posts its daily brief here. The owner reads it inside the Analyzer. One report per kind and date; re-runs replace it. |
| Meta clicks | Meta rows now fill `clicks` from link clicks. Migration 0017 backfills old rows, which showed 0. |

## Turning the key on

1. Create a key and its SHA-256 on your own computer:

   ```bash
   python -c "import secrets,hashlib; k=secrets.token_urlsafe(32); print('KEY', k); print('SHA256', hashlib.sha256(k.encode()).hexdigest())"
   ```

2. In Coolify, add the environment variable `ADVESTIQ_API_KEY_SHA256` with the SHA256 value (only the hash, never the key) and redeploy.
3. On the computer that runs ADVESTIQ, set two user environment variables, then restart the Claude app so scheduled tasks see them:

   ```bash
   setx ADVESTIQ_ANALYZER_KEY "<KEY>"
   setx ANALYZER_URL "https://<analyzer address>"
   ```

To revoke the key, remove `ADVESTIQ_API_KEY_SHA256` from Coolify (or replace it) and redeploy. Without the variable the header is rejected.

## Proposals

ADVESTIQ publishes every proposal (`P-…`, `D-…`) to the Analyzer. The owner sees them in the **Προτάσεις** tab of the ADVESTIQ page: list with filters, details, the email for the agency (copy it, or open it in the mail program), status buttons and comments. A link to `#advestiq/proposals/P-009` opens one proposal.

ADVESTIQ writes the content. Only the owner sets the status. Both add notes.

### Fields

| Field | Written by | Meaning |
| --- | --- | --- |
| `code` | ADVESTIQ (in the path) | `P-009`, `D-03`: 1–6 capital letters, a dash, 1–6 digits. Lower case is accepted and stored in capitals. |
| `title` | ADVESTIQ | Up to 300 characters. Required. |
| `platform` | ADVESTIQ | `google_ads`, `meta_ads`, `tiktok_ads`, `merchant_center`, `tracking` (GA4, GTM, pixels), `site`, `other`. Required. |
| `executor` | ADVESTIQ | `agency` (shown as «Συνεργάτης»), `owner` («Ιδιοκτήτης»), `site` («Υπεύθυνος του site»). Required. |
| `what`, `why`, `expected`, `rollback` | ADVESTIQ | Markdown, shown safely (no HTML). Up to 20,000 characters each. |
| `check_7_on`, `check_14_on` | ADVESTIQ | Dates of the 7- and 14-day checks, or `null`. |
| `message_subject`, `message_body` | ADVESTIQ | The email to the agency, plain text, in the owner's own words. «Αντιγραφή email» copies `Θέμα: <subject>`, a blank line, then the body. |
| `created_on` | ADVESTIQ | Date of the proposal. Required. |
| `advestiq_status` | ADVESTIQ | Free text, e.g. `για συζήτηση` or `ελέγχθηκε: εντός στόχου`. Up to 300 characters. |
| `status` | owner | See below. New proposals start as `discussion`. |
| `status_changed_at` | server | When the owner last changed the status. |
| `created_at`, `updated_at` | server | `updated_at` also moves when the owner changes the status. |

| `status` | Shown as | Open? |
| --- | --- | --- |
| `discussion` | Για συζήτηση | yes |
| `approved` | Εγκρίθηκε | yes |
| `sent` | Στάλθηκε στον συνεργάτη | yes |
| `done` | Έγινε | no |
| `not_done` | Δεν έγινε | no |
| `rejected` | Απορρίφθηκε | no |

A note has `id`, `author` (`owner` or `advestiq`), `text`, `status` and `created_at`. `status` is set only on the note the server writes when the owner changes the status; its `text` is the owner's optional comment and may be empty. Notes come in time order.

### Routes

| Route | Who | What it does |
| --- | --- | --- |
| `GET /api/advestiq/proposals?status=&platform=&full=` | owner, key | Open proposals first, then newest first. `status` takes a value above, or `open` / `closed`. Each row has the summary fields plus `notes_count` and `last_note_at`. `full=true` adds every field and the notes, for syncing. `counts` gives the number per status over all proposals. |
| `GET /api/advestiq/proposals/{code}` | owner, key | Every field and the notes. 404 if unknown. |
| `PUT /api/advestiq/proposals/{code}` | owner, key | Creates or updates the content fields only. Unknown fields, `status` included, are refused with 422, so a publish can never change the owner's decision or notes. The answer adds `created` and `changed` (false when nothing differed). |
| `POST /api/advestiq/proposals/{code}/notes` | owner, key | Body `{"text": "…"}`. The author follows the caller: the key writes `advestiq`, a login writes `owner`. Asking for the other author gives 403. |
| `PATCH /api/advestiq/proposals/{code}/status` | owner only | Body `{"status": "done", "note": "optional comment"}`. A new status is stored with a note. The same status with a note adds a plain note; without one it changes nothing. The key gets 403. |

All answers are wrapped as `{"data": …}`. Example publish (made-up):

```json
PUT /api/advestiq/proposals/P-009
{
  "title": "Μείωση προϋπολογισμού δοκιμαστικής καμπάνιας",
  "platform": "google_ads",
  "executor": "agency",
  "what": "Από 40 € σε 32 € την ημέρα.",
  "why": "…",
  "expected": "…",
  "rollback": "Επαναφορά στα 40 €.",
  "check_7_on": "2026-11-13",
  "check_14_on": "2026-11-20",
  "message_subject": "Αλλαγή προϋπολογισμού",
  "message_body": "Καλησπέρα σας,\nθα ήθελα…",
  "created_on": "2026-11-06",
  "advestiq_status": "για συζήτηση"
}
```

A sync tool can publish every ledger entry with `PUT` (unchanged entries answer `"changed": false`), then read the owner's side back with `GET /api/advestiq/proposals?full=true`: `status`, `status_changed_at` and the notes whose author is `owner`.

### What the key may write

`ADVESTIQ_WRITE_ROUTES` in `app/api/deps.py` lists one method and one full path pattern per route. Any other request that is not GET or HEAD gets 403 before the route runs:

- `POST /api/advestiq/reports`
- `PUT /api/advestiq/proposals/{code}`
- `POST /api/advestiq/proposals/{code}/notes`

The code in these paths may hold only letters, digits and dashes, so a path cannot reach another route. The status route also checks the caller itself (`require_owner`), so it refuses the key even if this list changes.

## Change history

The **Ιστορικό αλλαγών** page (main menu) shows every stored change of the ad platforms for a chosen period, grouped by Athens day: who made it, what changed and the detail, with old → new values where Google sends them (budgets in euros). Large automated batches, such as the nightly Google Ads feed upload, fold into one line per day and stay hidden until the owner asks for them. The filtered list can be downloaded as a CSV file for Excel.

`GET /api/business-review/changes` (owner, key):

| Parameter | Meaning |
| --- | --- |
| `date_from`, `date_to` | Required. Athens days, both included, at most 93 days. 400 otherwise. |
| `source` | One platform only: `google_ads`, `meta_ads`, or the source of manual evidence. |
| `actor` | One person only. `__none__` means changes without a recorded person. |
| `q` | Search in title, detail, person and object id, and in Google campaign names known from the daily metrics. Greek accents and capitals are ignored. Bulk groups match on their person, title and one sample row. |
| `include_bulk` | `true` adds the bulk groups. Default `false`. |
| `offset`, `limit` | Paging of the individual changes. Default 0 and 200; `limit` at most 1,000. |

A bulk group is 50 or more changes on the same Athens day with the same source, person, evidence type and title. Its rows never appear as individual changes.

```json
{
  "date_from": "2026-11-03", "date_to": "2026-11-06", "timezone": "Europe/Athens", "bulk_min_size": 50,
  "totals": {
    "changes": 169, "individual": 54, "bulk": 115, "bulk_groups": 2,
    "by_source": [{"source": "google_ads", "count": 168, "individual": 53, "bulk": 115}],
    "by_actor": [{"actor": "feed-bot@example.com", "count": 115, "individual": 0, "bulk": 115, "sources": ["google_ads"]}]
  },
  "filtered": {"individual": 54, "bulk": 115, "bulk_groups": 2},
  "bulk_groups": [{
    "day": "2026-11-05", "source": "google_ads", "actor": "feed-bot@example.com", "evidence_type": "api", "title": "CREATE",
    "count": 55, "first": "2026-11-05T02:39:00+00:00", "last": "2026-11-05T02:52:54+00:00",
    "sample": {"resource_type": "ASSET", "client_type": "GOOGLE_ADS_API", "detail": "asset", "object_id": "customers/1/assets/1"}
  }],
  "bulk_groups_truncated": false,
  "changes": [{
    "id": "…", "source": "google_ads", "occurred_at": "2026-11-05T09:15:00+00:00", "day": "2026-11-05",
    "evidence_type": "api", "actor": "manager@example.com", "title": "UPDATE", "detail": "amount_micros",
    "object_id": "customers/1/campaigns/111", "reference_url": null, "resource_type": "CAMPAIGN_BUDGET",
    "client_type": "GOOGLE_ADS_WEB_CLIENT", "campaign": "Δοκιμαστική καμπάνια", "payload": {"…": "the stored change event"}
  }],
  "offset": 0, "limit": 200, "has_more": false,
  "coverage": [{"source": "google_ads", "days_requested": 4, "days_covered": 3, "days_unavailable": 0, "days_failed": 0,
                "last_fetched_at": "2026-11-05T12:00:00+00:00"}]
}
```

- `totals` cover the whole window before `source`, `actor` and `q`; they also fill the page's filters. `filtered` counts what the filters keep: the individual changes (for paging) and the bulk groups.
- `changes` are the individual changes, newest first. `campaign` is the Google campaign name when the daily metrics know its id.
- `bulk_groups` are newest first, one per day and key, at most 1,000 (`bulk_groups_truncated`).
- `coverage` tells, for the providers whose change history is read, how many days of the window the history jobs have read, and when they last read it. Job error texts are not returned.

Speed: the grouping and the search for individual changes read only the index `ix_review_events_changes` (migration 0025), never the stored payloads. On a test database with 608,220 made-up events (93 nights of 6,500 feed rows plus 40 manual changes a day, 1.1 GB), a 30-day window answered in about 0.2 s, a 93-day window in about 0.5 s and a 93-day text search in about 0.6 s.

### Platforms without change history

The Analyzer reads change history only from Google Ads (change events, last 28 days) and Meta (ad-account activity log). The others have none here:

| Platform | In the Analyzer | Could its API provide it? |
| --- | --- | --- |
| TikTok Ads | Metrics only | Ads Manager keeps a change log per account, campaign, ad group and ad. Third-party docs mention Business API "change log" download tasks; not checked against TikTok's own reference. It would need a new connector. |
| Merchant Center | Product metrics and issues | No account change-history endpoint found. The Merchant API can send product status-change notifications from the moment one subscribes, which is not a history. |
| Google Tag Manager | Not connected | The GTM API v2 lists published container versions (`version_headers.list`), not who changed what. |
| GA4 settings | Not connected | The Admin API has `accounts.searchChangeHistoryEvents`: who changed which property setting, with before and after. A connector could read it. |

Until then, changes on these platforms can be added as evidence (one at a time or by CSV) on the Business review page; they then show up on this page too.
