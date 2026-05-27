from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.aade import AADEConnector
from app.connectors.ga4 import GA4Connector
from app.connectors.google_ads import GoogleAdsConnector
from app.connectors.merchant_center import MerchantCenterConnector
from app.connectors.meta_ads import MetaAdsConnector
from app.connectors.opencart import OpenCartConnector
from app.connectors.search_console import SearchConsoleConnector
from app.connectors.shoply import ShoplyConnector
from app.core.redaction import redact_sensitive
from app.models import IntegrationSetting, SyncRun
from app.services.constants import PROVIDERS, READ_ONLY_NOTICE
from app.services.import_service import (
    import_aade_payload,
    import_ga4_rows,
    import_google_ads_rows,
    import_merchant_rows,
    import_meta_ads_rows,
    import_opencart_orders,
    import_product_catalog,
    import_search_console_rows,
    import_shoply_sales,
)
from app.services.parsing import as_decimal, as_int
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


def merchant_sync_meta(rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [str(row.get("merchant_status") or "").upper() for row in rows]
    return {
        "merchant_rows": len(rows),
        "merchant_clicks": sum(as_int(row.get("clicks")) for row in rows),
        "merchant_impressions": sum(as_int(row.get("impressions")) for row in rows),
        "merchant_disapproved": sum(1 for status in statuses if "DISAPPROVED" in status),
        "merchant_limited": sum(1 for status in statuses if "LIMITED" in status),
        "merchant_pending": sum(1 for status in statuses if "PENDING" in status),
    }


def search_console_sync_meta(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "search_console_rows": len(rows),
        "search_console_clicks": sum(as_int(row.get("clicks")) for row in rows),
        "search_console_impressions": sum(as_int(row.get("impressions")) for row in rows),
    }


def _aade_record_type(row: dict[str, Any]) -> str:
    raw = row.get("raw")
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("record_type") or "")


def aade_sync_meta(payload: dict[str, Any]) -> dict[str, Any]:
    documents = payload.get("documents") if isinstance(payload, dict) else []
    summary_rows = payload.get("summary_rows") if isinstance(payload, dict) else []
    responses = payload.get("responses") if isinstance(payload, dict) else []
    if not isinstance(documents, list):
        documents = []
    if not isinstance(summary_rows, list):
        summary_rows = []
    income = sum(
        (as_decimal(row.get("gross_value")) for row in documents if row.get("document_direction") == "income"),
        Decimal("0"),
    )
    expenses = sum(
        (as_decimal(row.get("gross_value")) for row in documents if row.get("document_direction") == "expense"),
        Decimal("0"),
    )
    document_count = sum(as_int(row.get("document_count")) or 1 for row in documents)
    cancelled = sum(as_int(row.get("document_count")) or 1 for row in documents if row.get("is_cancelled"))
    full_documents = sum(1 for row in documents if not _aade_record_type(row))
    book_rows = [row for row in documents if _aade_record_type(row) == "book_info"]
    book_documents = sum(as_int(row.get("document_count")) or 1 for row in book_rows)
    vat_rows = [row for row in documents if _aade_record_type(row) == "vat_info"]
    vat_amount = sum((as_decimal(row.get("vat_amount")) for row in vat_rows), Decimal("0"))
    endpoint_results: dict[str, dict[str, Any]] = {}
    if isinstance(responses, list):
        for response in responses:
            if not isinstance(response, dict):
                continue
            endpoint = str(response.get("endpoint") or "unknown")
            row = endpoint_results.setdefault(
                endpoint,
                {
                    "calls": 0,
                    "full_documents": 0,
                    "book_rows": 0,
                    "book_documents": 0,
                    "vat_rows": 0,
                    "cancellations": 0,
                    "param_names": [],
                    "root_keys": [],
                    "raw_tags": [],
                    "record_samples": [],
                    "body_chars": 0,
                    "content_type": "",
                },
            )
            row["calls"] += 1
            row["full_documents"] += as_int(response.get("full_document_count"))
            row["book_rows"] += as_int(response.get("book_row_count"))
            row["book_documents"] += as_int(response.get("book_document_count"))
            row["vat_rows"] += as_int(response.get("vat_row_count"))
            row["cancellations"] += as_int(response.get("cancellation_count"))
            if not row["param_names"] and isinstance(response.get("request_param_names"), list):
                row["param_names"] = response["request_param_names"]
            shape = response.get("payload_shape")
            if isinstance(shape, dict):
                if not row["root_keys"] and isinstance(shape.get("root_keys"), list):
                    row["root_keys"] = shape["root_keys"]
                if not row["raw_tags"] and isinstance(shape.get("raw_tags"), list):
                    row["raw_tags"] = shape["raw_tags"]
                if not row["record_samples"] and isinstance(shape.get("record_samples"), list):
                    row["record_samples"] = shape["record_samples"]
                row["body_chars"] += as_int(shape.get("body_chars"))
                if not row["content_type"] and shape.get("content_type"):
                    row["content_type"] = str(shape.get("content_type"))
    return {
        "aade_documents": document_count,
        "aade_full_documents": full_documents,
        "aade_book_rows": len(book_rows),
        "aade_book_documents": book_documents,
        "aade_vat_rows": len(vat_rows),
        "aade_vat_amount": _json_number(vat_amount),
        "aade_summary_rows": len(summary_rows),
        "aade_calls": len(responses) if isinstance(responses, list) else 0,
        "aade_pages": len(responses) if isinstance(responses, list) else 0,
        "aade_endpoint_results": [
            {"endpoint": endpoint, **values} for endpoint, values in sorted(endpoint_results.items())
        ],
        "aade_gross_income": _json_number(income),
        "aade_gross_expenses": _json_number(expenses),
        "aade_cancelled_documents": cancelled,
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
            meta = merchant_sync_meta(rows)
        elif provider == "search_console":
            rows = SearchConsoleConnector(config).fetch_search_analytics(date_from, date_to)
            count = import_search_console_rows(db, rows, date_from)
            meta = search_console_sync_meta(rows)
        elif provider == "aade":
            connector_config = dict(config)
            if sync_type == "manual":
                connector_config["ignore_document_cursor"] = True
            payload = AADEConnector(connector_config).fetch_documents(date_from, date_to)
            count = import_aade_payload(db, payload, date_from)
            cursor = payload.get("cursor") if isinstance(payload, dict) else {}
            if isinstance(cursor, dict) and cursor:
                existing_cursor = config.get("cursor") if isinstance(config.get("cursor"), dict) else {}
                merged_cursor = dict(existing_cursor)
                for endpoint, endpoint_cursor in cursor.items():
                    if not isinstance(endpoint_cursor, dict):
                        continue
                    existing_mark = as_int(
                        existing_cursor.get(endpoint, {}).get("mark")
                        if isinstance(existing_cursor.get(endpoint), dict)
                        else None
                    )
                    new_mark = as_int(endpoint_cursor.get("mark"))
                    if new_mark > existing_mark:
                        merged_cursor[endpoint] = endpoint_cursor
                integration.config = {**config, "cursor": merged_cursor}
                db.add(integration)
            meta = aade_sync_meta(payload)
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
