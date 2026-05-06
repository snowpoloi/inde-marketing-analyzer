import csv
import io
from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import CampaignDailyMetric, GA4DailyMetric, MerchantProductMetric, OpenCartOrder, OpenCartOrderProduct, ShoplySale
from app.services.parsing import as_date, as_datetime, as_decimal, as_int


def _action_value(actions: list[dict[str, Any]] | None, action_type: str) -> int:
    if not actions:
        return 0
    for action in actions:
        if _action_matches(action.get("action_type"), action_type):
            return as_int(action.get("value"))
    return 0


def _money_action_value(actions: list[dict[str, Any]] | None, action_type: str):
    if not actions:
        return as_decimal(0)
    for action in actions:
        if _action_matches(action.get("action_type"), action_type):
            return as_decimal(action.get("value"))
    return as_decimal(0)


def _action_matches(actual: Any, expected: str) -> bool:
    value = str(actual or "")
    return value == expected or value.endswith(f".{expected}") or value.endswith(f"_{expected}")


def import_google_ads_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date") or row.get("day"), fallback_date) for row in rows} or {fallback_date}
    db.execute(
        delete(CampaignDailyMetric).where(
            CampaignDailyMetric.source == "google_ads",
            CampaignDailyMetric.metric_date.in_(touched_dates),
        )
    )

    for row in rows:
        metric_date = as_date(row.get("date") or row.get("day"), fallback_date)
        cost = as_decimal(row.get("cost"))
        conversion_value = as_decimal(row.get("conversion_value") or row.get("conversions_value"))
        conversions = as_decimal(row.get("conversions"))
        roas = as_decimal(row.get("roas"))
        if not conversion_value and roas and cost:
            conversion_value = roas * cost
        db.add(
            CampaignDailyMetric(
                source="google_ads",
                metric_date=metric_date,
                campaign_id=str(row.get("campaign_id") or "") or None,
                campaign_name=str(row.get("campaign_name") or "Unknown campaign"),
                campaign_type=row.get("campaign_type"),
                cost=cost,
                clicks=as_int(row.get("clicks")),
                impressions=as_int(row.get("impressions")),
                conversions=conversions,
                conversion_value=conversion_value,
                purchases=conversions,
                purchase_value=conversion_value,
                avg_cpc=as_decimal(row.get("avg_cpc")),
                cpc=as_decimal(row.get("avg_cpc") or row.get("cpc")),
                cost_per_conversion=as_decimal(row.get("cost_per_conversion")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_google_ads_csv(db: Session, text: str, fallback_date: date) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    return import_google_ads_rows(db, rows, fallback_date)


def import_meta_ads_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date") or row.get("date_start"), fallback_date) for row in rows} or {fallback_date}
    db.execute(
        delete(CampaignDailyMetric).where(
            CampaignDailyMetric.source == "meta_ads",
            CampaignDailyMetric.metric_date.in_(touched_dates),
        )
    )

    for row in rows:
        actions = row.get("actions") if isinstance(row.get("actions"), list) else None
        action_values = row.get("action_values") if isinstance(row.get("action_values"), list) else None
        purchases = as_decimal(row.get("purchases") or _action_value(actions, "purchase"))
        purchase_value = as_decimal(row.get("purchase_value") or _money_action_value(action_values, "purchase"))
        db.add(
            CampaignDailyMetric(
                source="meta_ads",
                metric_date=as_date(row.get("date") or row.get("date_start"), fallback_date),
                campaign_id=str(row.get("campaign_id") or "") or None,
                campaign_name=str(row.get("campaign_name") or "Unknown campaign"),
                adset_id=str(row.get("adset_id") or "") or None,
                adset_name=row.get("adset_name"),
                ad_id=str(row.get("ad_id") or "") or None,
                ad_name=row.get("ad_name"),
                cost=as_decimal(row.get("spend") or row.get("cost")),
                impressions=as_int(row.get("impressions")),
                reach=as_int(row.get("reach")),
                frequency=as_decimal(row.get("frequency")),
                link_clicks=as_int(row.get("link_clicks") or row.get("inline_link_clicks") or _action_value(actions, "link_click")),
                landing_page_views=as_int(row.get("landing_page_views") or _action_value(actions, "landing_page_view")),
                add_to_cart=as_int(row.get("add_to_cart") or _action_value(actions, "add_to_cart")),
                initiate_checkout=as_int(row.get("initiate_checkout") or _action_value(actions, "initiate_checkout")),
                purchases=purchases,
                purchase_value=purchase_value,
                conversions=purchases,
                conversion_value=purchase_value,
                cpc=as_decimal(row.get("cpc")),
                cpm=as_decimal(row.get("cpm")),
                ctr=as_decimal(row.get("ctr")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_meta_ads_csv(db: Session, text: str, fallback_date: date) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    return import_meta_ads_rows(db, rows, fallback_date)


def import_ga4_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date"), fallback_date) for row in rows} or {fallback_date}
    db.execute(delete(GA4DailyMetric).where(GA4DailyMetric.metric_date.in_(touched_dates)))
    for row in rows:
        db.add(
            GA4DailyMetric(
                metric_date=as_date(row.get("date"), fallback_date),
                channel_group=row.get("channel_group") or row.get("sessionDefaultChannelGroup"),
                source_medium=row.get("source_medium") or row.get("sessionSourceMedium"),
                sessions=as_int(row.get("sessions")),
                users=as_int(row.get("users") or row.get("totalUsers")),
                purchases=as_decimal(row.get("purchases")),
                purchase_revenue=as_decimal(row.get("purchase_revenue") or row.get("purchaseRevenue")),
                conversions=as_decimal(row.get("conversions")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_merchant_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date"), fallback_date) for row in rows} or {fallback_date}
    db.execute(delete(MerchantProductMetric).where(MerchantProductMetric.metric_date.in_(touched_dates)))
    for row in rows:
        db.add(
            MerchantProductMetric(
                metric_date=as_date(row.get("date"), fallback_date),
                item_id=str(row.get("item_id") or row.get("id") or row.get("offer_id") or ""),
                title=row.get("title") or row.get("name"),
                brand=row.get("brand"),
                category=row.get("category") or row.get("google_product_category") or row.get("product_type"),
                availability=row.get("availability"),
                price=as_decimal(row.get("price")),
                sale_price=as_decimal(row.get("sale_price")),
                clicks=as_int(row.get("clicks")),
                impressions=as_int(row.get("impressions")),
                ctr=as_decimal(row.get("ctr")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def _normalize_opencart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows or any(isinstance(row.get("products"), list) for row in rows):
        return rows
    if not any("product_id" in row or "product_name" in row for row in rows):
        return rows

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        if not order_id:
            continue
        order = grouped.setdefault(
            order_id,
            {
                **row,
                "shipping": row.get("shipping") or row.get("shipping_value"),
                "products": [],
            },
        )
        if row.get("product_id") or row.get("product_name"):
            order["products"].append(
                {
                    "product_id": row.get("product_id"),
                    "model": row.get("product_model"),
                    "sku": row.get("product_sku") or row.get("product_model"),
                    "name": row.get("product_name"),
                    "manufacturer": row.get("manufacturer") or row.get("brand"),
                    "brand": row.get("brand") or row.get("manufacturer"),
                    "category": row.get("category"),
                    "quantity": row.get("product_quantity"),
                    "price": row.get("product_price"),
                    "total": row.get("product_total"),
                    "mpn": row.get("product_mpn"),
                    "weight": row.get("product_weight"),
                }
            )
    return list(grouped.values())


def import_opencart_orders(db: Session, rows: list[dict[str, Any]]) -> int:
    normalized_rows = _normalize_opencart_rows(rows)
    for row in normalized_rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        if not order_id:
            continue
        order = db.query(OpenCartOrder).filter(OpenCartOrder.order_id == order_id).one_or_none()
        if not order:
            order = OpenCartOrder(order_id=order_id, date_added=as_datetime(row.get("date_added")), raw=row)
            db.add(order)
            db.flush()
        order.date_added = as_datetime(row.get("date_added"))
        order.order_status = row.get("order_status") or row.get("status")
        order.total = as_decimal(row.get("total"))
        order.shipping = as_decimal(row.get("shipping") or row.get("shipping_value"))
        order.payment_method = row.get("payment_method")
        order.raw = row
        order.products.clear()
        for product in row.get("products", []) or []:
            order.products.append(
                OpenCartOrderProduct(
                    product_id=str(product.get("product_id") or "") or None,
                    model=product.get("model"),
                    sku=product.get("sku"),
                    name=product.get("name") or "Unknown product",
                    manufacturer=product.get("manufacturer") or product.get("brand"),
                    brand=product.get("brand") or product.get("manufacturer"),
                    category=product.get("category"),
                    quantity=as_int(product.get("quantity")),
                    price=as_decimal(product.get("price")),
                    raw=product,
                )
            )
    db.commit()
    return len(normalized_rows)


def import_shoply_sales(db: Session, rows: list[dict[str, Any]]) -> int:
    for row in rows:
        db.add(
            ShoplySale(
                external_order_id=str(row.get("order_id") or row.get("id") or "") or None,
                sale_date=as_datetime(row.get("date") or row.get("date_added") or row.get("created_at")),
                status=row.get("status") or row.get("order_status"),
                total=as_decimal(row.get("total")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)
