# INDE Marketing Analyzer

Separate read-only reporting app for inde.gr. It is designed to run outside OpenCart on a Hetzner server through Coolify Docker Compose.

## Stack

- Backend: Python FastAPI
- Frontend: React/Vite served by Nginx
- Database: PostgreSQL
- Migrations: Alembic
- Worker: APScheduler daily sync
- Deployment: Docker Compose

The app never writes to Meta Ads, Google Ads, Merchant Center, OpenCart, Shoply, campaigns, budgets, products, or orders.

## Services

`docker-compose.yml` starts:

- `db`: PostgreSQL 16
- `backend`: FastAPI API on port 8000 inside the Compose network
- `worker`: daily provider sync
- `frontend`: Nginx static frontend and `/api` reverse proxy, exposed on port 3000

## Coolify Deployment

1. Create a new Coolify project from this repository/folder.
2. Use Docker Compose deployment.
3. Copy `.env.example` to `.env` and set production values:
   - `POSTGRES_PASSWORD`
   - `DATABASE_URL`
   - `SECRET_KEY`
   - `ADMIN_EMAIL`
   - `ADMIN_PASSWORD`
   - `CORS_ORIGINS`
4. Attach the public domain to the `frontend` service.
5. Keep the `pgdata` volume persistent.
6. Deploy. The backend runs `alembic upgrade head` on startup.

Example local start:

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: `http://localhost:3000`
- API health: `http://localhost:3000/health`
- API docs: `http://localhost:3000/api/docs`

## First Login

The backend creates the first admin user on startup when both are set:

```env
ADMIN_EMAIL=admin@inde.gr
ADMIN_PASSWORD=change-me-admin-password
```

Change these before production deployment.

## Integration Settings

Use the Settings page to enable providers and store JSON credentials.
For the MVP these credentials are stored in PostgreSQL, so restrict admin access and protect database backups.

### Meta Ads

```json
{
  "ad_account_id": "act_123456789",
  "access_token": "read-only-token",
  "graph_version": "v20.0"
}
```

### Google Ads

```json
{
  "developer_token": "...",
  "client_id": "...apps.googleusercontent.com",
  "client_secret": "...",
  "refresh_token": "...",
  "login_customer_id": "optional-manager-id",
  "customer_id": "1234567890"
}
```

### GA4

```json
{
  "property_id": "123456789",
  "service_account_json": {}
}
```

### Google Merchant Center

MVP supports a scheduled CSV export URL.

```json
{
  "csv_url": "https://example.com/merchant-report.csv"
}
```

### OpenCart

```json
{
  "endpoint_url": "https://inde.gr/index.php?route=api/marketing_analyzer/orders",
  "api_key": "optional-token"
}
```

### Shoply

```json
{
  "api_url": "https://example.com/shoply/orders",
  "api_key": "optional-token"
}
```

## OpenCart JSON Endpoint Contract

The analyzer calls the configured OpenCart endpoint with:

```text
GET /orders?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
Authorization: Bearer optional-token
```

Accepted JSON response:

```json
{
  "orders": [
    {
      "order_id": "12345",
      "date_added": "2026-05-05T13:42:00+03:00",
      "order_status": "Complete",
      "total": 89.9,
      "shipping": 3.5,
      "payment_method": "Card",
      "products": [
        {
          "product_id": "987",
          "model": "ABC-123",
          "sku": "SKU-123",
          "name": "Product name",
          "manufacturer": "Brand",
          "brand": "Brand",
          "category": "Category",
          "quantity": 2,
          "price": 43.2
        }
      ]
    }
  ]
}
```

The response may also be a plain array of orders.

## Main API Routes

Auth:

- `POST /api/auth/login`
- `GET /api/auth/me`

Settings:

- `GET /api/settings/integrations`
- `PUT /api/settings/integrations/{provider}`

Sync:

- `GET /api/sync/runs`
- `POST /api/sync/run`
- `POST /api/sync/import/google-ads-csv?report_date=YYYY-MM-DD`
- `POST /api/sync/import/meta-ads-csv?fallback_date=YYYY-MM-DD`
- `POST /api/sync/import/merchant-csv?report_date=YYYY-MM-DD`
- `POST /api/sync/import/opencart-json`
- `POST /api/sync/import/shoply-json`

Dashboard:

- `GET /api/dashboard/summary`
- `GET /api/dashboard/meta-performance`
- `GET /api/dashboard/google-performance`
- `GET /api/dashboard/opencart-sales`
- `GET /api/dashboard/attribution`
- `GET /api/dashboard/recommendations`
- `GET /api/dashboard/brand-category`
- `GET /api/dashboard/product-profitability`

All dashboard routes accept `date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`.

## CSV Imports

Google Ads CSV expected fields:

```csv
campaign_name,campaign_type,cost,clicks,impressions,conversions,conversion_value,roas,avg_cpc,cost_per_conversion
```

Optional `date` or `day` columns are also accepted. If missing, `report_date` is used.

Meta Ads CSV expected fields:

```csv
date,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,frequency,link_clicks,landing_page_views,add_to_cart,initiate_checkout,purchases,purchase_value,cpc,cpm,ctr
```

## Reporting Logic

- OpenCart is the source of truth for actual orders and revenue.
- Meta, Google Ads, and GA4 are attribution sources.
- Reconciliation compares:
  - Meta purchases
  - Google conversions
  - GA4 purchases
  - OpenCart orders
- Attribution delta is reported as absolute and percent variance against OpenCart orders.
- Recommendations are rule-based in the MVP:
  - `scale`
  - `reduce`
  - `pause`
  - `investigate tracking`
  - `investigate product/feed`

## Database Schema

Initial Alembic migration creates:

- `users`
- `integration_settings`
- `sync_runs`
- `campaign_daily_metrics`
- `ga4_daily_metrics`
- `merchant_product_metrics`
- `opencart_orders`
- `opencart_order_products`
- `shoply_sales`
- `campaign_recommendations`

## Development

Backend local:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend local:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`.
