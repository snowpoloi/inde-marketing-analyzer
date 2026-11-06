# ADVESTIQ access

ADVESTIQ is the read-only ad-agency assistant that runs in Claude Code on the owner's computer. It reads the Analyzer every morning, writes a brief and proposes changes. It never changes anything in the ad accounts or in the Analyzer.

## What this change adds

| Change | Why |
| --- | --- |
| `X-ADVESTIQ-Key` header (`app/api/deps.py`) | Lets ADVESTIQ read the API without a 24-hour login token. The key can only make GET requests, plus `POST /api/advestiq/reports`. It can never reach `/api/settings/integrations`, `/api/sync/*` or `/api/auth/*`. |
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
