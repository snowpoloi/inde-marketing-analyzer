from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, false, func, select
from sqlalchemy.orm import Session

from app.models import (
    AADEDocument,
    CampaignDailyMetric,
    GA4DailyMetric,
    IntegrationSetting,
    MerchantProductMetric,
    OpenCartOrder,
    OpenCartOrderChange,
    OpenCartOrderProduct,
    ProductCatalog,
    SearchConsoleDailyMetric,
)
from app.services.parsing import dec_to_float


def _period_filter(column, date_from: date, date_to: date):
    return and_(column >= date_from, column <= date_to)


def _ratio(numerator: Decimal | float | int, denominator: Decimal | float | int) -> float:
    denominator_float = float(denominator or 0)
    if denominator_float == 0:
        return 0.0
    return float(numerator or 0) / denominator_float


def _aade_document_count(document: AADEDocument) -> int:
    raw = document.raw if isinstance(document.raw, dict) else {}
    value = raw.get("document_count") or raw.get("count")
    if value in (None, ""):
        return 1
    try:
        return max(1, int(Decimal(str(value).replace(",", "."))))
    except (InvalidOperation, ValueError):
        return 1


def _aade_pick(row: Any, *keys: str) -> Any:
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key in row:
            return row[key]
        key_lower = key.lower()
        for row_key, value in row.items():
            if str(row_key).lower() == key_lower:
                return value
    return None


def _aade_text(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _aade_party_name(raw: dict[str, Any], party: str) -> str | None:
    header = _aade_pick(raw, "invoiceHeader", "header") or {}
    party_data = _aade_pick(raw, party) or _aade_pick(header, party) or {}
    name_keys = (
        "name",
        "legalName",
        "companyName",
        "businessName",
        "fullName",
        "partyName",
        "traderName",
        "description",
        "denomination",
        "eponymia",
    )
    prefixes = (party,)
    if party == "counterpart":
        prefixes = ("counterpart", "counterparty", "counter")
    direct_keys = tuple(
        key
        for prefix in prefixes
        for key in (
            f"{prefix}Name",
            f"{prefix}_name",
            f"{prefix}LegalName",
            f"{prefix}CompanyName",
            f"{prefix}BusinessName",
            f"{prefix}FullName",
            f"{prefix}Description",
        )
    )
    for candidate in (
        _aade_pick(party_data, *name_keys),
        _aade_pick(raw, *direct_keys),
        _aade_pick(header, *direct_keys),
    ):
        text = _aade_text(candidate)
        if text:
            return text
    return None


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


def _source_label(source: str) -> str:
    return {"meta_ads": "Meta Ads", "google_ads": "Google Ads"}.get(source, source)


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "positive": 4, "info": 5}.get(severity, 9)


def _audit_action(
    area: str,
    title: str,
    severity: str,
    action: str,
    reason: str,
    metric: str,
    value: str | int | float,
) -> dict[str, Any]:
    return {
        "area": area,
        "title": title,
        "severity": severity,
        "action": action,
        "reason": reason,
        "metric": metric,
        "value": value,
    }


def _merchant_raw_value(metric: MerchantProductMetric, key: str) -> Any:
    raw = metric.raw or {}
    if key in raw:
        return raw.get(key)
    product_health = raw.get("product_health") or {}
    product_view = product_health.get("productView") if isinstance(product_health, dict) else {}
    if not isinstance(product_view, dict):
        return None
    aliases = {
        "merchant_status": "aggregatedReportingContextStatus",
        "click_potential": "clickPotential",
        "product_status": "aggregatedReportingContextStatus",
    }
    return product_view.get(aliases.get(key, key))


def _merchant_metrics(db: Session, date_from: date, date_to: date) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    rows = db.scalars(
        select(MerchantProductMetric).where(_period_filter(MerchantProductMetric.metric_date, date_from, date_to))
    ).all()
    for row in rows:
        item_id = str(row.item_id or "").strip()
        if not item_id:
            continue
        current = metrics.setdefault(
            item_id,
            {
                "item_id": item_id,
                "title": row.title,
                "brand": row.brand,
                "category": row.category,
                "availability": row.availability,
                "merchant_status": _merchant_raw_value(row, "merchant_status"),
                "click_potential": _merchant_raw_value(row, "click_potential"),
                "price": dec_to_float(row.price),
                "clicks": 0,
                "impressions": 0,
            },
        )
        current["clicks"] += int(row.clicks or 0)
        current["impressions"] += int(row.impressions or 0)
        current["title"] = current["title"] or row.title
        current["brand"] = current["brand"] or row.brand
        current["category"] = current["category"] or row.category
        current["availability"] = current["availability"] or row.availability
        current["merchant_status"] = current["merchant_status"] or _merchant_raw_value(row, "merchant_status")
        current["click_potential"] = current["click_potential"] or _merchant_raw_value(row, "click_potential")
        if not current["price"]:
            current["price"] = dec_to_float(row.price)
    for metric in metrics.values():
        metric["ctr"] = _ratio(metric["clicks"], metric["impressions"]) * 100
    return metrics


def _tracking_audit(db: Session, date_from: date, date_to: date, summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = db.execute(
        select(
            func.coalesce(func.sum(CampaignDailyMetric.purchases), 0),
            func.coalesce(func.sum(CampaignDailyMetric.purchase_value), 0),
        ).where(
            CampaignDailyMetric.source == "meta_ads",
            _period_filter(CampaignDailyMetric.metric_date, date_from, date_to),
        )
    ).one()
    google = db.execute(
        select(
            func.coalesce(func.sum(CampaignDailyMetric.conversions), 0),
            func.coalesce(func.sum(CampaignDailyMetric.conversion_value), 0),
        ).where(
            CampaignDailyMetric.source == "google_ads",
            _period_filter(CampaignDailyMetric.metric_date, date_from, date_to),
        )
    ).one()
    ga4 = db.execute(
        select(
            func.coalesce(func.sum(GA4DailyMetric.purchases), 0),
            func.coalesce(func.sum(GA4DailyMetric.purchase_revenue), 0),
        ).where(_period_filter(GA4DailyMetric.metric_date, date_from, date_to))
    ).one()

    opencart_orders = float(summary.get("opencart_orders") or 0)
    opencart_revenue = float(summary.get("opencart_revenue") or 0)
    sources = [
        ("OpenCart", opencart_orders, opencart_revenue, "Source of truth"),
        ("GA4", float(ga4[0] or 0), float(ga4[1] or 0), "Site analytics"),
        ("Meta Ads", float(meta[0] or 0), float(meta[1] or 0), "Paid attribution"),
        ("Google Ads", float(google[0] or 0), float(google[1] or 0), "Paid attribution"),
    ]

    rows = []
    actions = []
    for name, orders, revenue, role in sources:
        order_delta = orders - opencart_orders
        revenue_delta = revenue - opencart_revenue
        order_coverage = _ratio(orders, opencart_orders) * 100 if name != "OpenCart" else 100
        revenue_coverage = _ratio(revenue, opencart_revenue) * 100 if name != "OpenCart" else 100
        status = "positive"
        recommendation = "Use as the sales and revenue baseline."
        if name != "OpenCart":
            status = "monitor"
            recommendation = "Keep comparing this attribution source against OpenCart."
            if opencart_orders and orders == 0:
                status = "high"
                recommendation = "No purchase signal for this period; check conversion setup and permissions."
            elif opencart_orders and order_coverage < 50:
                status = "high"
                recommendation = "Large attribution gap; review consent, purchase events and deduplication."
            elif opencart_orders and order_coverage < 80:
                status = "medium"
                recommendation = "Meaningful attribution gap; review tracking quality before scaling on this source alone."
            elif orders > 0:
                status = "positive"
                recommendation = "Purchase signal is flowing; use it as directional attribution."
        rows.append(
            {
                "source": name,
                "role": role,
                "reported_orders": orders,
                "reported_revenue": revenue,
                "opencart_orders": opencart_orders,
                "opencart_revenue": opencart_revenue,
                "orders_or_conversions": orders,
                "revenue": revenue,
                "order_delta": order_delta,
                "revenue_delta": revenue_delta,
                "order_coverage_percent": order_coverage,
                "revenue_coverage_percent": revenue_coverage,
                "status": status,
                "recommendation": recommendation,
            }
        )

    ga4_coverage = _ratio(ga4[0] or 0, opencart_orders) * 100
    if opencart_orders >= 10 and ga4_coverage < 75:
        actions.append(
            _audit_action(
                "Tracking",
                "GA4 under-reports purchases",
                "high",
                "investigate tracking",
                "GA4 purchases are materially below OpenCart orders. Check checkout purchase event, consent mode, and thank-you page firing.",
                "GA4 coverage",
                f"{ga4_coverage:.1f}%",
            )
        )

    paid_attributed_value = float(meta[1] or 0) + float(google[1] or 0)
    if opencart_revenue and paid_attributed_value > opencart_revenue * 1.25:
        actions.append(
            _audit_action(
                "Tracking",
                "Paid platforms may over-attribute revenue",
                "medium",
                "investigate tracking",
                "Meta and Google attributed revenue together exceed actual OpenCart revenue. Review duplicate conversions and attribution windows.",
                "Paid / actual revenue",
                f"{_ratio(paid_attributed_value, opencart_revenue):.2f}x",
            )
        )

    if opencart_orders and float(meta[0] or 0) == 0 and float(google[0] or 0) == 0:
        actions.append(
            _audit_action(
                "Tracking",
                "Paid conversion signals are missing",
                "high",
                "investigate tracking",
                "OpenCart has sales, but Meta and Google report no purchases/conversions in this period.",
                "Paid conversions",
                0,
            )
        )

    return {"rows": rows}, actions


def _campaign_audit(db: Session, date_from: date, date_to: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = source_performance(db, "meta_ads", date_from, date_to) + source_performance(db, "google_ads", date_from, date_to)
    audited = []
    actions = []
    for row in rows:
        source = _source_label(row["source"])
        cost = float(row["cost"] or 0)
        clicks = int(row["clicks"] or 0)
        impressions = int(row["impressions"] or 0)
        conversions = float(row["conversions"] or row.get("purchases") or 0)
        roas = float(row["roas"] or 0)
        ctr = float(row["ctr"] or 0)

        action = "monitor"
        severity = "low"
        reason = "Keep collecting data before making a budget decision."
        if cost >= 50 and clicks >= 100 and conversions == 0:
            action = "pause"
            severity = "high"
            reason = "Meaningful spend and clicks, but zero conversion signal."
        elif conversions >= 3 and roas >= 3:
            action = "scale"
            severity = "positive"
            reason = "Conversion volume and ROAS are strong enough to consider controlled scaling."
        elif cost >= 30 and 0 < roas < 1.5:
            action = "reduce"
            severity = "medium"
            reason = "Campaign spends but returns below the first profitability threshold."
        elif impressions >= 1000 and ctr < 0.5:
            action = "investigate product/feed"
            severity = "medium"
            reason = "Low CTR suggests creative, audience, query, or feed/product mismatch."
        elif cost > 0 and clicks == 0:
            action = "investigate tracking"
            severity = "medium"
            reason = "Spend exists without clicks; check imported metrics and campaign objective."

        audited_row = {
            **row,
            "source_label": source,
            "audit_action": action,
            "severity": severity,
            "reason": reason,
        }
        audited.append(audited_row)
        if severity in {"high", "medium", "positive"}:
            actions.append(
                _audit_action(
                    "Campaigns",
                    f"{source}: {row['campaign_name']}",
                    severity,
                    action,
                    reason,
                    "ROAS",
                    round(roas, 2),
                )
            )
    audited.sort(key=lambda item: (_severity_rank(item["severity"]), -float(item.get("cost") or 0)))
    return audited, actions


def _ga4_channel_audit(db: Session, date_from: date, date_to: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    channel_expr = func.coalesce(GA4DailyMetric.channel_group, "Unknown")
    source_expr = func.coalesce(GA4DailyMetric.source_medium, "Unknown")
    rows = db.execute(
        select(
            channel_expr.label("channel"),
            source_expr.label("source_medium"),
            func.coalesce(func.sum(GA4DailyMetric.sessions), 0).label("sessions"),
            func.coalesce(func.sum(GA4DailyMetric.users), 0).label("users"),
            func.coalesce(func.sum(GA4DailyMetric.purchases), 0).label("purchases"),
            func.coalesce(func.sum(GA4DailyMetric.purchase_revenue), 0).label("revenue"),
        )
        .where(_period_filter(GA4DailyMetric.metric_date, date_from, date_to))
        .group_by(channel_expr, source_expr)
        .order_by(func.sum(GA4DailyMetric.purchase_revenue).desc())
        .limit(50)
    ).all()
    audited = []
    actions = []
    for row in rows:
        sessions = int(row.sessions or 0)
        purchases = float(row.purchases or 0)
        revenue = float(row.revenue or 0)
        conversion_rate = _ratio(purchases, sessions) * 100
        revenue_per_session = _ratio(revenue, sessions)
        action = "monitor"
        severity = "low"
        reason = "Channel is within normal observation range."
        if sessions >= 200 and purchases == 0:
            action = "investigate tracking"
            severity = "medium"
            reason = "Traffic volume exists without purchase events; check landing pages, audience quality, or event tracking."
        elif purchases >= 10 and revenue_per_session >= 2:
            action = "scale"
            severity = "positive"
            reason = "Channel produces meaningful revenue per session."
        elif sessions >= 300 and conversion_rate < 0.3:
            action = "reduce"
            severity = "medium"
            reason = "Conversion rate is weak for the traffic volume."
        audited.append(
            {
                "channel": row.channel,
                "source_medium": row.source_medium,
                "sessions": sessions,
                "users": int(row.users or 0),
                "purchases": purchases,
                "revenue": dec_to_float(row.revenue),
                "conversion_rate": conversion_rate,
                "revenue_per_session": revenue_per_session,
                "audit_action": action,
                "severity": severity,
                "reason": reason,
            }
        )
        if severity in {"medium", "positive"}:
            actions.append(
                _audit_action(
                    "GA4",
                    f"{row.channel} / {row.source_medium}",
                    severity,
                    action,
                    reason,
                    "Conv. rate",
                    f"{conversion_rate:.2f}%",
                )
            )
    return audited, actions


def _search_console_audit(
    db: Session, date_from: date, date_to: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    query_expr = func.coalesce(SearchConsoleDailyMetric.query, "(not provided)")
    page_expr = func.coalesce(SearchConsoleDailyMetric.page, "-")
    rows = db.execute(
        select(
            query_expr.label("query"),
            page_expr.label("page"),
            func.coalesce(func.sum(SearchConsoleDailyMetric.clicks), 0).label("clicks"),
            func.coalesce(func.sum(SearchConsoleDailyMetric.impressions), 0).label("impressions"),
            func.coalesce(func.avg(SearchConsoleDailyMetric.position), 0).label("position"),
        )
        .where(_period_filter(SearchConsoleDailyMetric.metric_date, date_from, date_to))
        .group_by(query_expr, page_expr)
        .order_by(func.sum(SearchConsoleDailyMetric.clicks).desc(), func.sum(SearchConsoleDailyMetric.impressions).desc())
        .limit(80)
    ).all()

    audited = []
    actions = []
    for row in rows:
        clicks = int(row.clicks or 0)
        impressions = int(row.impressions or 0)
        ctr = _ratio(clicks, impressions) * 100
        position = float(row.position or 0)
        action = "monitor"
        severity = "low"
        reason = "Organic search signal is within normal monitoring range."
        if impressions >= 1000 and ctr < 1:
            action = "investigate seo"
            severity = "medium"
            reason = "High organic impressions with weak CTR; improve title/meta, offer clarity, or SERP snippet."
        elif impressions >= 500 and 10 < position <= 30:
            action = "optimize seo"
            severity = "medium"
            reason = "Query is near ranking distance; optimize landing page relevance and internal links."
        elif clicks >= 50 and ctr >= 2:
            action = "scale"
            severity = "positive"
            reason = "Query already brings organic clicks; connect it to products, paid campaigns, and content."
        elif position <= 5 and impressions >= 100:
            action = "protect"
            severity = "positive"
            reason = "Strong ranking position; protect page quality, stock, speed, and internal links."

        audited.append(
            {
                "query": row.query,
                "page": row.page,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "position": position,
                "audit_action": action,
                "severity": severity,
                "reason": reason,
            }
        )
        if severity in {"medium", "positive"}:
            actions.append(
                _audit_action(
                    "SEO",
                    str(row.query or row.page or "Search Console"),
                    severity,
                    action,
                    reason,
                    "Clicks / impressions",
                    f"{clicks} / {impressions}",
                )
            )
    audited.sort(
        key=lambda item: (
            _severity_rank(item["severity"]),
            -int(item.get("clicks") or 0),
            -int(item.get("impressions") or 0),
        )
    )
    return audited, actions


def _product_audit(db: Session, date_from: date, date_to: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    products = product_performance(db, date_from, date_to)
    merchant = _merchant_metrics(db, date_from, date_to)
    sales_by_key: set[str] = set()
    product_audit_rows = []
    actions = []

    for product in products:
        keys = {str(product.get("sku") or ""), str(product.get("model") or ""), str(product.get("product_id") or "")}
        keys = {key for key in keys if key}
        sales_by_key.update(keys)
        metric = next((merchant[key] for key in keys if key in merchant), None)
        orders = int(product.get("orders") or 0)
        quantity = int(product.get("quantity") or 0)
        revenue = float(product.get("revenue") or 0)
        impressions = int((metric or {}).get("impressions") or 0)
        clicks = int((metric or {}).get("clicks") or 0)
        average_quantity_per_order = float(product.get("average_quantity_per_order") or 0)

        action = "monitor"
        severity = "low"
        reason = "Keep as reference product; no strong action from current signals."
        if metric and metric.get("availability") and str(metric["availability"]).lower() not in {"in stock", "in_stock"}:
            action = "investigate product/feed"
            severity = "high"
            reason = "OpenCart has sales but Merchant availability is not in stock."
        elif orders >= 5 and impressions < 100:
            action = "investigate product/feed"
            severity = "high"
            reason = "Product sells across multiple orders but has weak Merchant visibility."
        elif orders >= 4 and revenue >= 500 and clicks < 10:
            action = "scale"
            severity = "positive"
            reason = "OpenCart demand is strong and paid/feed traffic is still low."
        elif orders <= 1 and quantity >= 5:
            action = "monitor"
            severity = "medium"
            reason = "Quantity came mostly from one order; wait for more distinct buyers before treating as winner."
        elif clicks >= 60 and orders == 0:
            action = "investigate product/feed"
            severity = "medium"
            reason = "Feed traffic exists without OpenCart sales."

        row = {
            **product,
            "merchant_clicks": clicks,
            "merchant_impressions": impressions,
            "merchant_ctr": float((metric or {}).get("ctr") or 0),
            "audit_action": action,
            "severity": severity,
            "reason": reason,
        }
        product_audit_rows.append(row)
        if severity in {"high", "medium", "positive"}:
            actions.append(
                _audit_action(
                    "Products",
                    str(product.get("name") or product.get("sku") or "Product"),
                    severity,
                    action,
                    reason,
                    "Orders / qty",
                    f"{orders} / {quantity} ({average_quantity_per_order:.2f} qty/order)",
                )
            )

    feed_rows = []
    for item in merchant.values():
        item_id = str(item.get("item_id") or "")
        clicks = int(item.get("clicks") or 0)
        impressions = int(item.get("impressions") or 0)
        ctr = float(item.get("ctr") or 0)
        has_sales = item_id in sales_by_key
        status = str(item.get("merchant_status") or "").upper()
        action = "monitor"
        severity = "low"
        reason = "Feed item is available for monitoring."
        if "DISAPPROVED" in status or "LIMITED" in status:
            action = "investigate product/feed"
            severity = "high"
            reason = "Merchant reports a product status that can limit delivery."
        elif clicks >= 50 and not has_sales:
            action = "investigate product/feed"
            severity = "medium"
            reason = "Product gets Merchant traffic but no matching OpenCart sales in this period."
        elif impressions >= 1000 and ctr < 0.5:
            action = "investigate product/feed"
            severity = "medium"
            reason = "High impressions with weak click-through rate."
        elif has_sales and impressions < 100:
            action = "scale"
            severity = "positive"
            reason = "Product sells but has limited Merchant visibility."
        feed_rows.append(
            {
                **item,
                "has_opencart_sales": has_sales,
                "audit_action": action,
                "severity": severity,
                "reason": reason,
            }
        )
        if severity in {"high", "medium"}:
            actions.append(
                _audit_action(
                    "Merchant feed",
                    str(item.get("title") or item_id),
                    severity,
                    action,
                    reason,
                    "Clicks / impressions",
                    f"{clicks} / {impressions}",
                )
            )

    product_audit_rows.sort(key=lambda item: (_severity_rank(item["severity"]), -float(item.get("revenue") or 0)))
    feed_rows.sort(key=lambda item: (_severity_rank(item["severity"]), -int(item.get("clicks") or 0)))
    return product_audit_rows[:80], feed_rows[:80], actions


def _operations_audit(db: Session, date_from: date, date_to: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sale_statuses = _configured_sale_statuses(db)
    status_expr = func.coalesce(OpenCartOrder.order_status, "Unknown")
    status_rows = db.execute(
        select(
            status_expr.label("status"),
            func.count(OpenCartOrder.id).label("orders"),
            func.coalesce(func.sum(OpenCartOrder.total), 0).label("revenue"),
        )
        .where(func.date(OpenCartOrder.date_added).between(date_from, date_to))
        .group_by(status_expr)
        .order_by(func.count(OpenCartOrder.id).desc())
    ).all()
    statuses = []
    actions = []
    for row in status_rows:
        normalized = str(row.status or "").strip().lower()
        counts_as_sale = True if sale_statuses is None else normalized in sale_statuses
        statuses.append(
            {
                "status": row.status,
                "orders": int(row.orders or 0),
                "revenue": dec_to_float(row.revenue),
                "counts_as_sale": counts_as_sale,
            }
        )
        if not counts_as_sale and int(row.orders or 0) >= 10:
            actions.append(
                _audit_action(
                    "Operations",
                    f"High volume non-sale status: {row.status}",
                    "medium",
                    "investigate operations",
                    "Many orders are in a status excluded from sales totals. Confirm whether the status rules match the business process.",
                    "Orders",
                    int(row.orders or 0),
                )
            )

    def grouped_order_rows(label_column, fallback: str, limit: int = 20) -> list[dict[str, Any]]:
        label_expr = func.coalesce(label_column, fallback)
        rows = db.execute(
            select(
                label_expr.label("label"),
                func.count(OpenCartOrder.id).label("orders"),
                func.coalesce(func.sum(OpenCartOrder.total), 0).label("revenue"),
                func.coalesce(func.avg(OpenCartOrder.total), 0).label("aov"),
            )
            .where(_opencart_sales_filter(db, date_from, date_to))
            .group_by(label_expr)
            .order_by(func.sum(OpenCartOrder.total).desc())
            .limit(limit)
        ).all()
        return [
            {
                "label": row.label,
                "orders": int(row.orders or 0),
                "revenue": dec_to_float(row.revenue),
                "aov": dec_to_float(row.aov),
            }
            for row in rows
        ]

    changes = db.execute(
        select(
            OpenCartOrderChange.field_name,
            func.count(OpenCartOrderChange.id).label("changes"),
            func.max(OpenCartOrderChange.detected_at).label("last_detected_at"),
        )
        .where(func.date(OpenCartOrderChange.detected_at).between(date_from, date_to))
        .group_by(OpenCartOrderChange.field_name)
        .order_by(func.count(OpenCartOrderChange.id).desc())
        .limit(20)
    ).all()

    return {
        "statuses": statuses,
        "payments": grouped_order_rows(OpenCartOrder.payment_method, "Unknown"),
        "shipping": grouped_order_rows(OpenCartOrder.shipping_method, "Unknown"),
        "customer_groups": grouped_order_rows(OpenCartOrder.customer_group, "Unknown"),
        "regions": grouped_order_rows(OpenCartOrder.shipping_zone, "Unknown"),
        "changes": [
            {
                "field": row.field_name,
                "changes": int(row.changes or 0),
                "last_detected_at": row.last_detected_at.isoformat() if row.last_detected_at else None,
            }
            for row in changes
        ],
    }, actions


def _aade_audit(
    db: Session,
    date_from: date,
    date_to: date,
    summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    documents = db.scalars(
        select(AADEDocument).where(_period_filter(AADEDocument.issue_date, date_from, date_to))
    ).all()

    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    income_documents = 0
    expense_documents = 0
    cancelled_documents = 0
    income_gross = Decimal("0")
    expense_gross = Decimal("0")
    income_vat = Decimal("0")
    expense_vat = Decimal("0")

    for document in documents:
        direction = document.document_direction or "unknown"
        invoice_type = document.invoice_type or "Unknown"
        document_count = _aade_document_count(document)
        key = (direction, invoice_type)
        row = rows_by_key.setdefault(
            key,
            {
                "direction": direction,
                "invoice_type": invoice_type,
                "documents": 0,
                "cancelled_documents": 0,
                "net_value": Decimal("0"),
                "vat_amount": Decimal("0"),
                "gross_value": Decimal("0"),
            },
        )
        row["documents"] += document_count
        if document.is_cancelled:
            row["cancelled_documents"] += document_count
            cancelled_documents += document_count
        else:
            row["net_value"] += document.net_value or Decimal("0")
            row["vat_amount"] += document.vat_amount or Decimal("0")
            row["gross_value"] += document.gross_value or Decimal("0")

        if direction == "income":
            income_documents += document_count
            if not document.is_cancelled:
                income_gross += document.gross_value or Decimal("0")
                income_vat += document.vat_amount or Decimal("0")
        elif direction == "expense":
            expense_documents += document_count
            if not document.is_cancelled:
                expense_gross += document.gross_value or Decimal("0")
                expense_vat += document.vat_amount or Decimal("0")

    opencart_orders = int(summary.get("opencart_orders") or 0)
    opencart_revenue = Decimal(str(summary.get("opencart_revenue") or 0))
    revenue_gap = income_gross - opencart_revenue
    revenue_gap_percent = _ratio(revenue_gap, opencart_revenue) * 100 if opencart_revenue else 0

    actions: list[dict[str, Any]] = []
    if opencart_revenue and not income_documents:
        actions.append(
            _audit_action(
                "AADE",
                "AADE income documents missing",
                "high",
                "investigate fiscal",
                "OpenCart has sales in this period, but no AADE income documents were imported.",
                "OpenCart revenue",
                dec_to_float(opencart_revenue),
            )
        )
    elif opencart_revenue and abs(revenue_gap_percent) > 10:
        actions.append(
            _audit_action(
                "AADE",
                "AADE and OpenCart revenue mismatch",
                "high",
                "investigate fiscal",
                "AADE income gross differs from OpenCart sales by more than 10%. Check date range, statuses and document matching.",
                "Revenue gap",
                dec_to_float(revenue_gap),
            )
        )
    elif opencart_revenue and abs(revenue_gap_percent) > 3:
        actions.append(
            _audit_action(
                "AADE",
                "AADE and OpenCart revenue variance",
                "medium",
                "investigate fiscal",
                "AADE income gross differs from OpenCart sales by more than 3%. This may be timing, cancelled orders or status rules.",
                "Revenue gap",
                dec_to_float(revenue_gap),
            )
        )
    elif opencart_revenue and income_documents:
        actions.append(
            _audit_action(
                "AADE",
                "AADE income aligns with OpenCart",
                "positive",
                "monitor",
                "AADE income documents are close to OpenCart sales for this period.",
                "Revenue gap",
                dec_to_float(revenue_gap),
            )
        )

    if cancelled_documents >= 3:
        actions.append(
            _audit_action(
                "AADE",
                "AADE cancellations require review",
                "medium",
                "investigate fiscal",
                "Several AADE documents are marked cancelled in this period. Compare them with OpenCart cancelled/returned statuses.",
                "Cancelled documents",
                cancelled_documents,
            )
        )

    rows = []
    for row in rows_by_key.values():
        cancelled = int(row["cancelled_documents"])
        gross_value = row["gross_value"]
        action = "monitor"
        severity = "low"
        reason = "Fiscal documents are stored for read-only monitoring."
        if row["direction"] == "income" and not gross_value and int(row["documents"]) > cancelled:
            action = "investigate fiscal"
            severity = "medium"
            reason = "Income documents exist but imported gross value is zero. Check myDATA payload mapping."
        elif cancelled:
            action = "investigate fiscal"
            severity = "medium"
            reason = "This document group includes cancellations."
        rows.append(
            {
                **row,
                "net_value": dec_to_float(row["net_value"]),
                "vat_amount": dec_to_float(row["vat_amount"]),
                "gross_value": dec_to_float(gross_value),
                "audit_action": action,
                "severity": severity,
                "reason": reason,
            }
        )

    rows.sort(key=lambda item: (_severity_rank(item["severity"]), item["direction"], item["invoice_type"]))
    audit_summary = {
        "income_documents": income_documents,
        "expense_documents": expense_documents,
        "cancelled_documents": cancelled_documents,
        "income_gross": dec_to_float(income_gross),
        "expense_gross": dec_to_float(expense_gross),
        "income_vat": dec_to_float(income_vat),
        "expense_vat": dec_to_float(expense_vat),
        "opencart_orders": opencart_orders,
        "opencart_revenue": dec_to_float(opencart_revenue),
        "revenue_gap": dec_to_float(revenue_gap),
        "revenue_gap_percent": revenue_gap_percent,
    }

    return {"summary": audit_summary, "documents": rows[:80], "mismatches": actions}, actions


def aade_document_ledger(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    documents = db.scalars(
        select(AADEDocument)
        .where(_period_filter(AADEDocument.issue_date, date_from, date_to))
        .order_by(
            AADEDocument.issue_date.desc(),
            AADEDocument.document_direction,
            AADEDocument.invoice_type,
            AADEDocument.series,
            AADEDocument.aa,
            AADEDocument.mark,
        )
    ).all()

    rows = []
    categories: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        raw = document.raw if isinstance(document.raw, dict) else {}
        document_count = _aade_document_count(document)
        direction = document.document_direction or "unknown"
        invoice_type = document.invoice_type or "Unknown"
        record_type = str(raw.get("record_type") or "full_document")
        issuer_name = _aade_party_name(raw, "issuer")
        if not issuer_name and record_type == "book_info" and direction == "expense":
            issuer_name = _aade_party_name(raw, "counterpart")
        category_key = (direction, invoice_type)
        category = categories.setdefault(
            category_key,
            {
                "direction": direction,
                "invoice_type": invoice_type,
                "documents": 0,
                "net_value": Decimal("0"),
                "vat_amount": Decimal("0"),
                "gross_value": Decimal("0"),
            },
        )
        category["documents"] += document_count
        if not document.is_cancelled:
            category["net_value"] += document.net_value or Decimal("0")
            category["vat_amount"] += document.vat_amount or Decimal("0")
            category["gross_value"] += document.gross_value or Decimal("0")

        rows.append(
            {
                "source_endpoint": document.source_endpoint,
                "record_type": record_type,
                "direction": direction,
                "invoice_type": invoice_type,
                "document_count": document_count,
                "mark": document.mark,
                "uid": document.uid,
                "issue_date": document.issue_date.isoformat(),
                "issuer_vat": document.issuer_vat,
                "issuer_name": issuer_name,
                "counterpart_vat": document.counterpart_vat,
                "series": document.series,
                "aa": document.aa,
                "currency": document.currency or "EUR",
                "net_value": dec_to_float(document.net_value),
                "vat_amount": dec_to_float(document.vat_amount),
                "gross_value": dec_to_float(document.gross_value),
                "is_cancelled": document.is_cancelled,
                "cancelled_by_mark": document.cancelled_by_mark,
                "identity_key": document.identity_key,
            }
        )

    return {
        "rows": rows,
        "categories": [
            {
                **row,
                "net_value": dec_to_float(row["net_value"]),
                "vat_amount": dec_to_float(row["vat_amount"]),
                "gross_value": dec_to_float(row["gross_value"]),
            }
            for row in categories.values()
        ],
    }


def _empty_summary(date_from: date, date_to: date) -> dict[str, Any]:
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ad_spend": 0,
        "ad_clicks": 0,
        "ad_impressions": 0,
        "attributed_conversions": 0,
        "attributed_revenue": 0,
        "opencart_orders": 0,
        "opencart_revenue": 0,
        "shipping_revenue": 0,
        "ga4_purchases": 0,
        "ga4_revenue": 0,
        "actual_roas": 0,
        "attributed_roas": 0,
        "aov": 0,
    }


def _empty_operations_audit() -> dict[str, Any]:
    return {
        "statuses": [],
        "payments": [],
        "shipping": [],
        "customer_groups": [],
        "regions": [],
        "changes": [],
    }


def _empty_aade_audit() -> dict[str, Any]:
    return {
        "summary": {
            "income_documents": 0,
            "expense_documents": 0,
            "cancelled_documents": 0,
            "income_gross": 0,
            "expense_gross": 0,
            "income_vat": 0,
            "expense_vat": 0,
            "opencart_orders": 0,
            "opencart_revenue": 0,
            "revenue_gap": 0,
            "revenue_gap_percent": 0,
        },
        "documents": [],
        "mismatches": [],
    }


def _audit_section_failure(area: str, exc: Exception) -> dict[str, Any]:
    action = {
        "AADE": "investigate fiscal",
        "Operations": "investigate operations",
    }.get(area, "investigate tracking")
    return _audit_action(
        area,
        f"{area} audit could not be calculated",
        "high",
        action,
        f"This audit section failed on the server ({type(exc).__name__}). The rest of the audit remains available; check backend logs for the exact query.",
        "Section",
        area,
    )


def _safe_audit_section(db: Session, area: str, fallback: Any, callback):
    try:
        return callback(), None
    except Exception as exc:
        db.rollback()
        return fallback, _audit_section_failure(area, exc)


def marketing_audit(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    priority_actions = []

    summary, failure = _safe_audit_section(
        db,
        "Summary",
        _empty_summary(date_from, date_to),
        lambda: executive_summary(db, date_from, date_to),
    )
    if failure:
        priority_actions.append(failure)

    tracking_result, failure = _safe_audit_section(
        db,
        "Tracking",
        ({"rows": []}, []),
        lambda: _tracking_audit(db, date_from, date_to, summary),
    )
    tracking, tracking_actions = tracking_result
    if failure:
        priority_actions.append(failure)

    campaign_result, failure = _safe_audit_section(
        db,
        "Campaigns",
        ([], []),
        lambda: _campaign_audit(db, date_from, date_to),
    )
    campaigns, campaign_actions = campaign_result
    if failure:
        priority_actions.append(failure)

    channel_result, failure = _safe_audit_section(
        db,
        "GA4",
        ([], []),
        lambda: _ga4_channel_audit(db, date_from, date_to),
    )
    channels, channel_actions = channel_result
    if failure:
        priority_actions.append(failure)

    search_console_result, failure = _safe_audit_section(
        db,
        "Search Console",
        ([], []),
        lambda: _search_console_audit(db, date_from, date_to),
    )
    search_console, search_console_actions = search_console_result
    if failure:
        priority_actions.append(failure)

    product_result, failure = _safe_audit_section(
        db,
        "Products",
        ([], [], []),
        lambda: _product_audit(db, date_from, date_to),
    )
    products, feed, product_actions = product_result
    if failure:
        priority_actions.append(failure)

    aade_result, failure = _safe_audit_section(
        db,
        "AADE",
        (_empty_aade_audit(), []),
        lambda: _aade_audit(db, date_from, date_to, summary),
    )
    aade, aade_actions = aade_result
    if failure:
        priority_actions.append(failure)

    operations_result, failure = _safe_audit_section(
        db,
        "Operations",
        (_empty_operations_audit(), []),
        lambda: _operations_audit(db, date_from, date_to),
    )
    operations, operation_actions = operations_result
    if failure:
        priority_actions.append(failure)

    priority_actions.extend(
        tracking_actions
        + campaign_actions
        + channel_actions
        + search_console_actions
        + product_actions
        + aade_actions
        + operation_actions
    )
    if not priority_actions and summary.get("opencart_orders", 0):
        priority_actions.append(
            _audit_action(
                "Overall",
                "No critical blockers found",
                "positive",
                "monitor",
                "The connected data does not show a severe issue for this period. Keep daily sync running and review winners weekly.",
                "OpenCart orders",
                int(summary.get("opencart_orders") or 0),
            )
        )
    priority_actions.sort(key=lambda item: (_severity_rank(item["severity"]), item["area"], item["title"]))

    high_count = sum(1 for item in priority_actions if item["severity"] in {"critical", "high"})
    medium_count = sum(1 for item in priority_actions if item["severity"] == "medium")
    positive_count = sum(1 for item in priority_actions if item["severity"] == "positive")
    readiness_score = max(0, 100 - high_count * 18 - medium_count * 7 + min(positive_count * 3, 12))

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "overview": {
            "readiness_score": readiness_score,
            "high_priority": high_count,
            "medium_priority": medium_count,
            "positive_signals": positive_count,
            "actual_revenue": summary.get("opencart_revenue", 0),
            "actual_orders": summary.get("opencart_orders", 0),
            "ad_spend": summary.get("ad_spend", 0),
            "actual_roas": summary.get("actual_roas", 0),
        },
        "priority_actions": priority_actions[:30],
        "tracking": tracking,
        "campaigns": campaigns,
        "channels": channels,
        "search_console": search_console,
        "products": products,
        "feed": feed,
        "aade": aade,
        "operations": operations,
    }
