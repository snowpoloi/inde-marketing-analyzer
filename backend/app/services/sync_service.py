from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.ga4 import GA4Connector
from app.connectors.google_ads import GoogleAdsConnector
from app.connectors.merchant_center import MerchantCenterConnector
from app.connectors.meta_ads import MetaAdsConnector
from app.connectors.opencart import OpenCartConnector
from app.connectors.shoply import ShoplyConnector
from app.core.redaction import redact_sensitive
from app.models import IntegrationSetting, SyncRun
from app.services.constants import PROVIDERS, READ_ONLY_NOTICE
from app.services.import_service import (
    import_ga4_rows,
    import_google_ads_rows,
    import_merchant_rows,
    import_meta_ads_rows,
    import_opencart_orders,
    import_product_catalog,
    import_shoply_sales,
)
from app.services.parsing import as_decimal
from app.services.product_catalog_service import enrich_order_products_from_catalog


def default_sync_window() -> tuple[date, date]:
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    return yesterday, yesterday


def get_integration(db: Session, provider: str) -> IntegrationSetting | None:
    return db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))


def start_run(db: Session, provider: str, sync_type: str, date_from: date, date_to: date) -> SyncRun:
    run = SyncRun(
        provider=provider,
        sync_type=sync_type,
        status="running",
        date_from=date_from,
        date_to=date_to,
        meta={"notice": READ_ONLY_NOTICE},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(db: Session, run: SyncRun, status: str, records: int = 0, error: str | None = None, meta: dict[str, Any] | None = None) -> SyncRun:
    run.status = status
    run.records_processed = records
    run.error_message = redact_sensitive(error)
    run.finished_at = datetime.now(timezone.utc)
    if meta:
        run.meta = {**(run.meta or {}), **meta}
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _json_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    return int(integral) if value == integral else float(value)


def ga4_sync_meta(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    purchases = sum((as_decimal(row.get("purchases") or row.get("ecommercePurchases")) for row in rows), Decimal("0"))
    revenue = sum(
        (as_decimal(row.get("purchase_revenue") or row.get("purchaseRevenue")) for row in rows),
        Decimal("0"),
    )
    return {
        "ga4_rows": len(rows),
        "ga4_purchases": _json_number(purchases),
        "ga4_purchase_revenue": _json_number(revenue),
    }


def run_provider_sync(
    db: Session,
    provider: str,
    date_from: date | None = None,
    date_to: date | None = None,
    sync_type: str = "manual",
) -> SyncRun:
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    window_from, window_to = default_sync_window()
    date_from = date_from or window_from
    date_to = date_to or window_to
    run = start_run(db, provider, sync_type, date_from, date_to)
    integration = get_integration(db, provider)
    if not integration or not integration.is_enabled:
        return finish_run(db, run, "skipped", 0, meta={"reason": "Integration is disabled."})

    try:
        config = integration.config or {}
        meta = None
        if provider == "opencart":
            connector = OpenCartConnector(config)
            product_count = 0
            order_count = 0
            order_product_updates = 0
            product_feed_error = None
            order_error = None
            try:
                product_rows = connector.fetch_product_catalog()
                product_count = import_product_catalog(db, product_rows)
                db.commit()
                order_product_updates = enrich_order_products_from_catalog(db)
            except Exception as exc:
                db.rollback()
                product_feed_error = str(exc)
            if connector.endpoint_url:
                try:
                    rows = connector.fetch_orders(date_from, date_to)
                    order_count = import_opencart_orders(db, rows)
                except Exception as exc:
                    db.rollback()
                    order_error = str(exc)
            count = product_count + order_count
        elif provider == "meta_ads":
            rows = MetaAdsConnector(config).fetch_campaign_metrics(date_from, date_to)
            count = import_meta_ads_rows(db, rows, date_from)
        elif provider == "google_ads":
            rows = GoogleAdsConnector(config).fetch_campaign_metrics(date_from, date_to)
            count = import_google_ads_rows(db, rows, date_from)
        elif provider == "ga4":
            rows = GA4Connector(config).fetch_daily_metrics(date_from, date_to)
            count = import_ga4_rows(db, rows, date_from)
            meta = ga4_sync_meta(rows)
        elif provider == "merchant_center":
            rows = MerchantCenterConnector(config).fetch_product_metrics(date_from, date_to)
            count = import_merchant_rows(db, rows, date_from)
        elif provider == "shoply":
            rows = ShoplyConnector(config).fetch_sales(date_from, date_to)
            count = import_shoply_sales(db, rows)
        else:
            count = 0
        if provider == "opencart":
            meta = {
                "product_catalog_records": product_count,
                "order_records": order_count,
                "order_product_updates": order_product_updates,
            }
            if product_feed_error:
                meta["product_feed_error"] = product_feed_error
            if order_error:
                return finish_run(db, run, "failed", count, error=order_error, meta=meta)
            if product_feed_error and connector.product_feed_url and order_count == 0:
                return finish_run(db, run, "failed", count, error=product_feed_error, meta=meta)
        return finish_run(db, run, "success", count, meta=meta)
    except Exception as exc:
        db.rollback()
        run = db.get(SyncRun, run.id)
        return finish_run(db, run, "failed", 0, error=str(exc))


def run_many(db: Session, providers: list[str] | None, date_from: date | None, date_to: date | None, sync_type: str = "manual") -> list[SyncRun]:
    selected = providers or list(PROVIDERS.keys())
    return [run_provider_sync(db, provider, date_from, date_to, sync_type=sync_type) for provider in selected]
