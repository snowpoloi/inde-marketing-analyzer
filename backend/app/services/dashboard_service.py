from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, false, func, select
from sqlalchemy.orm import Session

from app.models import (
    CampaignDailyMetric,
    GA4DailyMetric,
    IntegrationSetting,
    MerchantProductMetric,
    OpenCartOrder,
    OpenCartOrderProduct,
    ProductCatalog,
)
from app.services.parsing import dec_to_float


def _period_filter(column, date_from: date, date_to: date):
    return and_(column >= date_from, column <= date_to)


def _ratio(numerator: Decimal | float | int, denominator: Decimal | float | int) -> float:
    denominator_float = float(denominator or 0)
    if denominator_float == 0:
        return 0.0
    return float(numerator or 0) / denominator_float


def _configured_sale_statuses(db: Session) -> list[str] | None:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "opencart"))
    config = integration.config if integration else {}
    rules = (config or {}).get("order_status_rules") or []
    if not rules:
        return None
    return [
        str(rule.get("name") or "").strip().lower()
        for rule in rules
        if isinstance(rule, dict)
        if rule.get("counts_as_sale") and str(rule.get("name") or "").strip()
    ]


def _opencart_sales_filter(db: Session, date_from: date, date_to: date):
    conditions = [func.date(OpenCartOrder.date_added).between(date_from, date_to)]
    sale_statuses = _configured_sale_statuses(db)
    if sale_statuses is not None:
        if not sale_statuses:
            conditions.append(false())
        else:
            status_expr = func.lower(func.trim(func.coalesce(OpenCartOrder.order_status, "")))
            conditions.append(status_expr.in_(sale_statuses))
    return and_(*conditions)


def executive_summary(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    ad_row = db.execute(
        select(
            func.coalesce(func.sum(CampaignDailyMetric.cost), 0),
            func.coalesce(func.sum(CampaignDailyMetric.clicks), 0),
            func.coalesce(func.sum(CampaignDailyMetric.impressions), 0),
            func.coalesce(func.sum(CampaignDailyMetric.conversions), 0),
            func.coalesce(func.sum(CampaignDailyMetric.conversion_value), 0),
        ).where(_period_filter(CampaignDailyMetric.metric_date, date_from, date_to))
    ).one()
    order_row = db.execute(
        select(
            func.count(OpenCartOrder.id),
            func.coalesce(func.sum(OpenCartOrder.total), 0),
            func.coalesce(func.sum(OpenCartOrder.shipping), 0),
        ).where(_opencart_sales_filter(db, date_from, date_to))
    ).one()
    ga4_row = db.execute(
        select(
            func.coalesce(func.sum(GA4DailyMetric.purchases), 0),
            func.coalesce(func.sum(GA4DailyMetric.purchase_revenue), 0),
        ).where(_period_filter(GA4DailyMetric.metric_date, date_from, date_to))
    ).one()

    ad_spend = ad_row[0]
    actual_revenue = order_row[1]
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ad_spend": dec_to_float(ad_spend),
        "ad_clicks": int(ad_row[1] or 0),
        "ad_impressions": int(ad_row[2] or 0),
        "attributed_conversions": dec_to_float(ad_row[3]),
        "attributed_revenue": dec_to_float(ad_row[4]),
        "opencart_orders": int(order_row[0] or 0),
        "opencart_revenue": dec_to_float(actual_revenue),
        "shipping_revenue": dec_to_float(order_row[2]),
        "ga4_purchases": dec_to_float(ga4_row[0]),
        "ga4_revenue": dec_to_float(ga4_row[1]),
        "actual_roas": _ratio(actual_revenue, ad_spend),
        "attributed_roas": _ratio(ad_row[4], ad_spend),
        "aov": _ratio(actual_revenue, order_row[0]),
    }


def source_performance(db: Session, source: str, date_from: date, date_to: date) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            CampaignDailyMetric.campaign_id,
            CampaignDailyMetric.campaign_name,
            func.coalesce(func.sum(CampaignDailyMetric.cost), 0).label("cost"),
            func.coalesce(func.sum(CampaignDailyMetric.clicks), 0).label("clicks"),
            func.coalesce(func.sum(CampaignDailyMetric.impressions), 0).label("impressions"),
            func.coalesce(func.sum(CampaignDailyMetric.conversions), 0).label("conversions"),
            func.coalesce(func.sum(CampaignDailyMetric.conversion_value), 0).label("conversion_value"),
            func.coalesce(func.sum(CampaignDailyMetric.purchases), 0).label("purchases"),
            func.coalesce(func.sum(CampaignDailyMetric.purchase_value), 0).label("purchase_value"),
        )
        .where(CampaignDailyMetric.source == source, _period_filter(CampaignDailyMetric.metric_date, date_from, date_to))
        .group_by(CampaignDailyMetric.campaign_id, CampaignDailyMetric.campaign_name)
        .order_by(func.sum(CampaignDailyMetric.cost).desc())
    ).all()
    return [
        {
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "source": source,
            "cost": dec_to_float(row.cost),
            "clicks": int(row.clicks or 0),
            "impressions": int(row.impressions or 0),
            "conversions": dec_to_float(row.conversions),
            "conversion_value": dec_to_float(row.conversion_value),
            "purchases": dec_to_float(row.purchases),
            "purchase_value": dec_to_float(row.purchase_value),
            "roas": _ratio(row.conversion_value or row.purchase_value, row.cost),
            "cpc": _ratio(row.cost, row.clicks),
            "ctr": _ratio(row.clicks, row.impressions) * 100,
        }
        for row in rows
    ]


def opencart_sales(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    daily_rows = db.execute(
        select(
            func.date(OpenCartOrder.date_added).label("day"),
            func.count(OpenCartOrder.id).label("orders"),
            func.coalesce(func.sum(OpenCartOrder.total), 0).label("revenue"),
        )
        .where(_opencart_sales_filter(db, date_from, date_to))
        .group_by(func.date(OpenCartOrder.date_added))
        .order_by(func.date(OpenCartOrder.date_added))
    ).all()
    return {
        "daily": [
            {"date": str(row.day), "orders": int(row.orders or 0), "revenue": dec_to_float(row.revenue)}
            for row in daily_rows
        ],
        "summary": executive_summary(db, date_from, date_to),
    }


def attribution_comparison(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    meta_purchases = db.scalar(
        select(func.coalesce(func.sum(CampaignDailyMetric.purchases), 0)).where(
            CampaignDailyMetric.source == "meta_ads",
            _period_filter(CampaignDailyMetric.metric_date, date_from, date_to),
        )
    )
    google_conversions = db.scalar(
        select(func.coalesce(func.sum(CampaignDailyMetric.conversions), 0)).where(
            CampaignDailyMetric.source == "google_ads",
            _period_filter(CampaignDailyMetric.metric_date, date_from, date_to),
        )
    )
    ga4_purchases = db.scalar(
        select(func.coalesce(func.sum(GA4DailyMetric.purchases), 0)).where(
            _period_filter(GA4DailyMetric.metric_date, date_from, date_to)
        )
    )
    opencart_orders_count = db.scalar(
        select(func.count(OpenCartOrder.id)).where(_opencart_sales_filter(db, date_from, date_to))
    )
    actual = int(opencart_orders_count or 0)

    sources = [
        ("Meta purchases", meta_purchases or 0),
        ("Google conversions", google_conversions or 0),
        ("GA4 purchases", ga4_purchases or 0),
        ("OpenCart orders", actual),
    ]
    rows = []
    for label, value in sources:
        delta = float(value or 0) - actual
        rows.append(
            {
                "source": label,
                "reported": dec_to_float(value),
                "opencart_orders": actual,
                "delta": delta,
                "delta_percent": _ratio(delta, actual) * 100 if actual else 0,
            }
        )
    return {"rows": rows, "source_of_truth": "OpenCart orders"}


def brand_category_performance(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    base_filter = _opencart_sales_filter(db, date_from, date_to)
    brand_expr = func.coalesce(OpenCartOrderProduct.brand, OpenCartOrderProduct.manufacturer, "Unknown")
    category_expr = func.coalesce(OpenCartOrderProduct.category, "Unknown")
    brand_rows = db.execute(
        select(
            brand_expr.label("brand"),
            func.coalesce(func.sum(OpenCartOrderProduct.quantity), 0).label("quantity"),
            func.coalesce(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity), 0).label("revenue"),
        )
        .join(OpenCartOrder, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
        .where(base_filter)
        .group_by(brand_expr)
        .order_by(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity).desc())
        .limit(20)
    ).all()
    category_rows = db.execute(
        select(
            category_expr.label("category"),
            func.coalesce(func.sum(OpenCartOrderProduct.quantity), 0).label("quantity"),
            func.count(func.distinct(OpenCartOrder.id)).label("orders"),
            func.coalesce(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity), 0).label("revenue"),
        )
        .join(OpenCartOrder, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
        .where(base_filter)
        .group_by(category_expr)
        .order_by(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity).desc())
        .limit(20)
    ).all()
    return {
        "brands": [
            {"brand": row.brand, "quantity": int(row.quantity or 0), "revenue": dec_to_float(row.revenue)}
            for row in brand_rows
        ],
        "categories": [
            {"category": row.category, "quantity": int(row.quantity or 0), "revenue": dec_to_float(row.revenue)}
            for row in category_rows
        ],
    }


def product_profitability_hints(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    brand_expr = func.coalesce(OpenCartOrderProduct.brand, OpenCartOrderProduct.manufacturer, "Unknown")
    category_expr = func.coalesce(OpenCartOrderProduct.category, "Unknown")
    rows = db.execute(
        select(
            OpenCartOrderProduct.product_id,
            OpenCartOrderProduct.sku,
            OpenCartOrderProduct.name,
            brand_expr.label("brand"),
            category_expr.label("category"),
            func.coalesce(func.sum(OpenCartOrderProduct.quantity), 0).label("quantity"),
            func.count(func.distinct(OpenCartOrder.id)).label("orders"),
            func.coalesce(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity), 0).label("revenue"),
        )
        .join(OpenCartOrder, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
        .where(_opencart_sales_filter(db, date_from, date_to))
        .group_by(
            OpenCartOrderProduct.product_id,
            OpenCartOrderProduct.sku,
            OpenCartOrderProduct.name,
            brand_expr,
            category_expr,
        )
        .order_by(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity).desc())
        .limit(50)
    ).all()

    merchant_by_item = {
        row.item_id: row
        for row in db.execute(
            select(MerchantProductMetric).where(_period_filter(MerchantProductMetric.metric_date, date_from, date_to))
        ).scalars()
    }

    hints = []
    for row in rows:
        merchant = merchant_by_item.get(row.sku or "") or merchant_by_item.get(row.product_id or "")
        order_count = int(row.orders or 0)
        average_quantity_per_order = _ratio(row.quantity, order_count)
        action = "monitor"
        reason = "Sales exist; add margin/COGS to turn this into net profit."
        if merchant and merchant.availability and merchant.availability.lower() not in {"in stock", "in_stock"}:
            action = "investigate product/feed"
            reason = f"OpenCart has sales, but Merchant availability is {merchant.availability}."
        elif order_count <= 1 and row.quantity >= 5:
            action = "monitor"
            reason = "Bulk quantity from one order; wait for more distinct orders before treating it as strong demand."
        elif order_count >= 3 and row.quantity >= 5 and row.revenue > 0:
            action = "scale"
            reason = "Sales came from multiple orders; stronger demand signal than a single bulk purchase."
        elif row.quantity <= 1:
            action = "reduce"
            reason = "Low sales volume; review margin, feed quality, price, and campaign match."
        hints.append(
            {
                "product_id": row.product_id,
                "sku": row.sku,
                "name": row.name,
                "brand": row.brand,
                "category": row.category,
                "quantity": int(row.quantity or 0),
                "orders": order_count,
                "average_quantity_per_order": average_quantity_per_order,
                "revenue": dec_to_float(row.revenue),
                "hint": action,
                "reason": reason,
            }
        )
    return hints


def product_performance(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            OpenCartOrderProduct.product_id,
            OpenCartOrderProduct.sku,
            OpenCartOrderProduct.model,
            OpenCartOrderProduct.name,
            OpenCartOrderProduct.brand,
            OpenCartOrderProduct.manufacturer,
            OpenCartOrderProduct.category,
            func.coalesce(func.sum(OpenCartOrderProduct.quantity), 0).label("quantity"),
            func.count(func.distinct(OpenCartOrder.id)).label("orders"),
            func.coalesce(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity), 0).label("revenue"),
            func.max(OpenCartOrder.date_added).label("last_sold_at"),
        )
        .join(OpenCartOrder, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
        .where(_opencart_sales_filter(db, date_from, date_to))
        .group_by(
            OpenCartOrderProduct.product_id,
            OpenCartOrderProduct.sku,
            OpenCartOrderProduct.model,
            OpenCartOrderProduct.name,
            OpenCartOrderProduct.brand,
            OpenCartOrderProduct.manufacturer,
            OpenCartOrderProduct.category,
        )
        .order_by(func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity).desc())
        .limit(300)
    ).all()

    catalog_lookup = {
        product.sku: product
        for product in db.scalars(select(ProductCatalog)).all()
        if product.sku
    }
    results = []
    for row in rows:
        catalog = catalog_lookup.get(row.sku or "")
        brand = row.brand or row.manufacturer or (catalog.brand if catalog else None) or "Unknown"
        category = row.category or (catalog.category if catalog else None) or "Unknown"
        results.append(
            {
                "product_id": row.product_id,
                "sku": row.sku,
                "model": row.model,
                "name": row.name,
                "brand": brand,
                "category": category,
                "quantity": int(row.quantity or 0),
                "orders": int(row.orders or 0),
                "revenue": dec_to_float(row.revenue),
                "average_unit_price": _ratio(row.revenue, row.quantity),
                "average_quantity_per_order": _ratio(row.quantity, row.orders),
                "last_sold_at": row.last_sold_at.isoformat() if row.last_sold_at else None,
                "catalog_status": catalog.status if catalog else None,
                "catalog_quantity": catalog.quantity if catalog else None,
                "catalog_price": dec_to_float(catalog.price) if catalog else None,
                "image_url": catalog.image_url if catalog else None,
                "link": catalog.link if catalog else None,
            }
        )
    return results


def campaign_recommendations(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    rows = source_performance(db, "meta_ads", date_from, date_to) + source_performance(db, "google_ads", date_from, date_to)
    recommendations = []
    for row in rows:
        if row["cost"] <= 0:
            continue
        action = "investigate tracking"
        severity = "medium"
        reason = "Campaign has spend but limited conversion signal."
        if row["cost"] >= 50 and row["clicks"] >= 100 and row["conversions"] == 0:
            action = "pause"
            severity = "high"
            reason = "Spend and clicks are significant, but reported conversions are zero."
        elif row["roas"] >= 3 and row["conversions"] >= 3:
            action = "scale"
            severity = "positive"
            reason = "ROAS and conversion volume are above MVP scale threshold."
        elif row["cost"] >= 30 and 0 < row["roas"] < 1.5:
            action = "reduce"
            severity = "medium"
            reason = "ROAS is below MVP efficiency threshold."
        elif row["clicks"] > 0 and row["impressions"] > 0 and row["ctr"] < 0.5:
            action = "investigate product/feed"
            severity = "medium"
            reason = "CTR is weak; check creative, query match, or feed/product quality."

        recommendations.append(
            {
                "source": "Meta Ads" if row["source"] == "meta_ads" else "Google Ads",
                "campaign_id": row["campaign_id"],
                "campaign_name": row["campaign_name"],
                "action": action,
                "severity": severity,
                "reason": reason,
                "metrics": row,
            }
        )
    return recommendations
