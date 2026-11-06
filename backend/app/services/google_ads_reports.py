"""Google Ads detail reports: search terms, products and Performance Max asset groups.

The sync stores the costliest rows of each day (limits in app.connectors.google_ads). Conversions and
conversion value are what Google Ads reports, not OpenCart orders. Ratios are null when their denominator is 0.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, distinct, func, insert, or_, select
from sqlalchemy.orm import Session

from app.connectors.google_ads import (
    CUSTOM_LABELS,
    PERFORMANCE_MAX,
    PRODUCTS_PER_DAY,
    SEARCH_TERM_CAMPAIGN_TYPES,
    SEARCH_TERMS_PER_DAY,
)
from app.models import (
    CampaignDailyMetric,
    GoogleAdsAssetGroupDailyMetric,
    GoogleAdsProductDailyMetric,
    GoogleAdsSearchTermDailyMetric,
    ProductCatalog,
)
from app.services.detail_reports import _count, _money, _rate, _window_days
from app.services.parsing import as_date, as_decimal, as_int

SEARCH_TERMS_NOTE = (
    f"Up to {SEARCH_TERMS_PER_DAY} Search and Shopping rows (per ad group and match type) and up to "
    f"{SEARCH_TERMS_PER_DAY} Performance Max rows (per campaign) are stored per day, the costliest first. Google "
    "hides search terms with too few searches, so stored cost is below campaign cost; cost_coverage shows the "
    "share. Performance Max terms have no ad group, keyword status or real match type. Conversions are what "
    "Google Ads reports, not OpenCart orders."
)
PRODUCTS_NOTE = (
    f"Up to {PRODUCTS_PER_DAY} product + campaign rows are stored per day, the costliest first, for Shopping and "
    "Performance Max. Product rows count products shown in ads, so they do not add up to campaign totals; "
    "cost_coverage shows the share. Products are matched to the OpenCart catalog by SKU, product_id or model, "
    "ignoring case. Conversions are what Google Ads reports, not OpenCart orders."
)
ASSET_GROUPS_NOTE = (
    "Performance Max results per asset group, as Google Ads reports them. Conversions are not OpenCart orders."
)
CATALOG_KEYS = ("sku", "product_id", "model")
METRIC_FIELDS = ("impressions", "clicks", "cost", "conversions", "conversion_value")


# ---------------------------------------------------------------- helpers


def _label(value: Any, max_length: int, empty: str | None = None) -> str | None:
    text = str(value or "").strip()
    return text[:max_length] if text else empty


def _empty() -> dict[str, Any]:
    return {"impressions": 0, "clicks": 0, "cost": Decimal("0"), "conversions": Decimal("0"),
            "conversion_value": Decimal("0")}


def _add(bucket: dict[str, Any], row: Any) -> None:
    """Add a stored row (attributes) or a connector row (dict keys) to a bucket."""
    get = row.get if isinstance(row, dict) else lambda name: getattr(row, name)
    bucket["impressions"] += as_int(get("impressions"))
    bucket["clicks"] += as_int(get("clicks"))
    for field in ("cost", "conversions", "conversion_value"):
        bucket[field] += as_decimal(get(field))


def _no_conversions(bucket: dict[str, Any]) -> bool:
    return bucket["cost"] > 0 and bucket["conversions"] == 0


def _metrics(bucket: dict[str, Any]) -> dict[str, Any]:
    cost, clicks, impressions = bucket["cost"], bucket["clicks"], bucket["impressions"]
    return {
        "impressions": impressions,
        "clicks": clicks,
        "cost": _money(cost),
        "conversions": _count(bucket["conversions"]),
        "conversion_value": _money(bucket["conversion_value"]),
        "ctr": _rate(clicks * 100, impressions),
        "cpc": _rate(cost, clicks, 2),
        "cost_per_conversion": _rate(cost, bucket["conversions"], 2),
        "conversion_value_per_cost": _rate(bucket["conversion_value"], cost),
    }


def _window(date_from: date, date_to: date) -> set[date]:
    return {date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)}


def _replace(db: Session, model: Any, values: list[dict[str, Any]], date_from: date, date_to: date) -> int:
    """Replace every stored day of the synced window, so a day that now has fewer rows loses its stale ones."""
    days = _window(date_from, date_to) | {item["metric_date"] for item in values}
    db.execute(delete(model).where(model.metric_date.in_(days)))
    if values:
        db.execute(insert(model), values)
    db.commit()
    return len(values)


def _campaign_filter(model: Any, campaign: str) -> Any:
    return or_(model.campaign_id == campaign, func.lower(model.campaign_name) == campaign.strip().lower())


def _sums(model: Any) -> list[Any]:
    return [func.coalesce(func.sum(getattr(model, field)), 0).label(field) for field in METRIC_FIELDS]


def _stored_days(db: Session, model: Any, conditions: list[Any]) -> set[date]:
    return set(db.scalars(select(model.metric_date).where(*conditions).distinct()).all())


def _latest(db: Session, model: Any, key: Any, columns: list[Any], conditions: list[Any]) -> dict[str, Any]:
    """The newest row's `columns` per `key` (latest day, then most impressions), so a rename shows the new name."""
    ranked = (
        select(key.label("key"), *columns, func.row_number().over(
            partition_by=key, order_by=(model.metric_date.desc(), model.impressions.desc())).label("rank"))
        .where(*conditions)
        .subquery()
    )
    return {row.key: row for row in db.execute(select(ranked).where(ranked.c.rank == 1)).all()}


def _campaign_names(db: Session, model: Any, conditions: list[Any]) -> dict[str, dict[str, Any]]:
    latest = _latest(db, model, model.campaign_id, [model.campaign_name, model.campaign_type], conditions)
    return {key: {"campaign_name": row.campaign_name, "campaign_type": row.campaign_type} for key, row in latest.items()}


def _pair(campaign_id: str, names: dict[str, dict[str, Any]], row: Any) -> dict[str, Any]:
    """A campaign bucket with the summed metrics of a GROUP BY row."""
    pair = {"campaign_id": campaign_id, "campaign_name": None, "campaign_type": None, **names.get(campaign_id, {}),
            **_empty()}
    _add(pair, row)
    return pair


def _campaign_costs(db: Session, days: set[date], campaign_types: tuple[str, ...], campaign: str | None = None):
    """Campaign-level Google Ads cost per campaign (from the campaign sync) on the given days."""
    if not days:
        return {}
    query = (
        select(CampaignDailyMetric.campaign_id, func.coalesce(func.sum(CampaignDailyMetric.cost), 0))
        .where(
            CampaignDailyMetric.source == "google_ads",
            CampaignDailyMetric.metric_date.in_(days),
            CampaignDailyMetric.campaign_type.in_(campaign_types),
        )
        .group_by(CampaignDailyMetric.campaign_id)
    )
    if campaign:
        query = query.where(_campaign_filter(CampaignDailyMetric, campaign))
    return {str(campaign_id or ""): Decimal(cost) for campaign_id, cost in db.execute(query).all()}


def _coverage(stored_cost: Decimal, campaign_costs: dict[str, Decimal], days: set[date]) -> dict[str, Any]:
    campaign_cost = sum(campaign_costs.values(), Decimal("0")) if days else None
    return {
        "campaign_cost": _money(campaign_cost) if campaign_cost is not None else None,
        "cost_coverage": _rate(stored_cost, campaign_cost),
    }


def _campaign_rows(campaigns: dict[str, dict[str, Any]], campaign_costs: dict[str, Decimal], extra=None):
    rows = []
    for item in sorted(campaigns.values(), key=lambda value: (-value["cost"], value["campaign_id"])):
        cost = campaign_costs.get(item["campaign_id"])
        rows.append({
            "campaign_id": item["campaign_id"],
            "campaign_name": item["campaign_name"],
            "campaign_type": item["campaign_type"],
            **(extra(item) if extra else {}),
            **_metrics(item),
            "campaign_cost": _money(cost) if cost is not None else None,
            "cost_coverage": _rate(item["cost"], cost),
        })
    return rows


# ---------------------------------------------------------------- imports


def import_search_term_rows(db: Session, rows: list[dict[str, Any]], date_from: date, date_to: date) -> int:
    merged: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        search_term = _label(row.get("search_term"), 500)
        if not search_term:
            continue
        key = (
            as_date(row.get("date"), date_from),
            _label(row.get("campaign_id"), 64, ""),
            _label(row.get("ad_group_id"), 64, ""),
            search_term,
            _label(row.get("match_type"), 32, ""),
        )
        item = merged.get(key)
        if item is None:
            item = merged[key] = {
                "metric_date": key[0], "campaign_id": key[1], "ad_group_id": key[2], "search_term": key[3],
                "match_type": key[4],
                "campaign_name": _label(row.get("campaign_name"), 255, "Unknown campaign"),
                "campaign_type": _label(row.get("campaign_type"), 40),
                "ad_group_name": _label(row.get("ad_group_name"), 255),
                "status": _label(row.get("status"), 32),
                **_empty(),
            }
        _add(item, row)
    return _replace(db, GoogleAdsSearchTermDailyMetric, list(merged.values()), date_from, date_to)


def import_product_rows(db: Session, rows: list[dict[str, Any]], date_from: date, date_to: date) -> int:
    """A product whose title or labels changed during a day comes as several rows: they are added up, and the
    attributes of the row with the most impressions are kept."""
    merged: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        item_id = _label(row.get("item_id"), 160)
        if not item_id:
            continue
        key = (as_date(row.get("date"), date_from), _label(row.get("campaign_id"), 64, ""), item_id)
        attributes = {
            "campaign_name": _label(row.get("campaign_name"), 255, "Unknown campaign"),
            "campaign_type": _label(row.get("campaign_type"), 40),
            "title": _label(row.get("title"), 500),
            "brand": _label(row.get("brand"), 255),
            **{f"custom_label_{index}": _label(row.get(f"custom_label_{index}"), 255) for index in CUSTOM_LABELS},
        }
        item = merged.get(key)
        if item is None:
            item = merged[key] = {"metric_date": key[0], "campaign_id": key[1], "item_id": item_id, **attributes,
                                  **_empty(), "_impressions": -1}
        if as_int(row.get("impressions")) > item["_impressions"]:
            item.update(attributes, _impressions=as_int(row.get("impressions")))
        _add(item, row)
    values = [{key: value for key, value in item.items() if key != "_impressions"} for item in merged.values()]
    return _replace(db, GoogleAdsProductDailyMetric, values, date_from, date_to)


def import_asset_group_rows(db: Session, rows: list[dict[str, Any]], date_from: date, date_to: date) -> int:
    merged: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        asset_group_id = _label(row.get("asset_group_id"), 64)
        if not asset_group_id:
            continue
        key = (as_date(row.get("date"), date_from), asset_group_id)
        item = merged.get(key)
        if item is None:
            item = merged[key] = {
                "metric_date": key[0], "asset_group_id": asset_group_id,
                "campaign_id": _label(row.get("campaign_id"), 64, ""),
                "campaign_name": _label(row.get("campaign_name"), 255, "Unknown campaign"),
                "asset_group_name": _label(row.get("asset_group_name"), 255, "Unknown asset group"),
                "asset_group_status": _label(row.get("asset_group_status"), 32),
                **_empty(),
            }
        _add(item, row)
    return _replace(db, GoogleAdsAssetGroupDailyMetric, list(merged.values()), date_from, date_to)


# ---------------------------------------------------------------- search terms


def search_term_report(
    db: Session,
    date_from: date,
    date_to: date,
    campaign: str | None = None,
    limit: int = 100,
    no_conversions_only: bool = False,
) -> dict[str, Any]:
    model = GoogleAdsSearchTermDailyMetric
    conditions = [model.metric_date.between(date_from, date_to)]
    if campaign:
        conditions.append(_campaign_filter(model, campaign))
    days = _stored_days(db, model, conditions)
    names = _campaign_names(db, model, conditions)

    # Aggregated in SQL: one row per term, then one per term and campaign.
    terms: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        select(model.search_term, func.count(distinct(model.metric_date)).label("days"),
               func.array_agg(distinct(model.match_type)).label("match_types"),
               func.array_agg(distinct(model.status)).label("statuses"))
        .where(*conditions)
        .group_by(model.search_term)
    ).all():
        terms[row.search_term] = {
            "search_term": row.search_term, "days": row.days, "campaigns": [],
            "match_types": sorted(value for value in row.match_types if value),
            "statuses": sorted(value for value in row.statuses if value),
            **_empty(),
        }
    totals = _empty()
    campaigns: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        select(model.search_term, model.campaign_id, *_sums(model))
        .where(*conditions)
        .group_by(model.search_term, model.campaign_id)
    ).all():
        pair = _pair(row.campaign_id, names, row)
        term = terms[row.search_term]
        term["campaigns"].append(pair)
        stored_campaign = campaigns.setdefault(row.campaign_id, {
            **{key: pair[key] for key in ("campaign_id", "campaign_name", "campaign_type")},
            "terms": 0, "no_conversion_cost": Decimal("0"), **_empty()})
        stored_campaign["terms"] += 1
        if _no_conversions(pair):
            stored_campaign["no_conversion_cost"] += pair["cost"]
        for bucket in (totals, term, stored_campaign):
            _add(bucket, pair)

    wasted = [term for term in terms.values() if _no_conversions(term)]
    ranked = sorted(wasted if no_conversions_only else terms.values(),
                    key=lambda item: (-item["cost"], -item["clicks"], item["search_term"]))
    campaign_costs = _campaign_costs(db, days, (*SEARCH_TERM_CAMPAIGN_TYPES, PERFORMANCE_MAX), campaign)

    def term_row(term: dict[str, Any]) -> dict[str, Any]:
        stored = sorted(term["campaigns"], key=lambda item: (-item["cost"], item["campaign_id"]))
        return {
            "search_term": term["search_term"],
            "days": term["days"],
            "match_types": term["match_types"],
            "statuses": term["statuses"],
            "campaign_types": sorted({item["campaign_type"] for item in stored if item["campaign_type"]}),
            **_metrics(term),
            "no_conversions": _no_conversions(term),
            "campaigns": [
                {"campaign_id": item["campaign_id"], "campaign_name": item["campaign_name"],
                 "campaign_type": item["campaign_type"], **_metrics(item), "no_conversions": _no_conversions(item)}
                for item in stored
            ],
        }

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "campaign": campaign,
        "no_conversions_only": no_conversions_only,
        **_window_days(date_from, date_to, days),
        "stored_rows_per_day": {"search_and_shopping": SEARCH_TERMS_PER_DAY, "performance_max": SEARCH_TERMS_PER_DAY},
        "totals": {
            "terms": len(terms),
            **_metrics(totals),
            "no_conversion_terms": len(wasted),
            "no_conversion_cost": _money(sum((term["cost"] for term in wasted), Decimal("0"))),
        },
        **_coverage(totals["cost"], campaign_costs, days),
        "terms": [term_row(term) for term in ranked[:limit]],
        "by_campaign": _campaign_rows(campaigns, campaign_costs, lambda item: {
            "terms": item["terms"], "no_conversion_cost": _money(item["no_conversion_cost"])}),
        "note": SEARCH_TERMS_NOTE,
    }


# ---------------------------------------------------------------- products


def _catalog_matches(db: Session, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    """OpenCart catalog products per lower-case item ID. SKU matches win over product_id, then model."""
    keys = {item_id.strip().lower() for item_id in item_ids if item_id and item_id.strip()}
    if not keys:
        return {}
    rows = db.execute(
        select(ProductCatalog.sku, ProductCatalog.product_id, ProductCatalog.model, ProductCatalog.name,
               ProductCatalog.brand, ProductCatalog.category, ProductCatalog.price, ProductCatalog.quantity,
               ProductCatalog.status, ProductCatalog.link)
        .where(or_(*(func.lower(func.trim(getattr(ProductCatalog, field))).in_(keys) for field in CATALOG_KEYS)))
    ).all()
    matches: dict[str, dict[str, Any]] = {}
    for field in CATALOG_KEYS:
        for row in sorted(rows, key=lambda item: item.sku):
            key = str(getattr(row, field) or "").strip().lower()
            if key in keys and key not in matches:
                matches[key] = {
                    "matched_by": field, "sku": row.sku, "product_id": row.product_id, "model": row.model,
                    "name": row.name, "brand": row.brand, "category": row.category, "price": _money(row.price),
                    "quantity": row.quantity, "status": row.status, "link": row.link,
                }
    return matches


def product_report(
    db: Session, date_from: date, date_to: date, limit: int = 100, no_conversions_only: bool = False
) -> dict[str, Any]:
    model = GoogleAdsProductDailyMetric
    conditions = [model.metric_date.between(date_from, date_to)]
    days = _stored_days(db, model, conditions)
    names = _campaign_names(db, model, conditions)
    labels = [getattr(model, f"custom_label_{index}") for index in CUSTOM_LABELS]

    # Aggregated in SQL: the latest attributes and the day count per product, then metrics per product and campaign.
    products: dict[str, dict[str, Any]] = {}
    for item_id, row in _latest(db, model, model.item_id, [model.title, model.brand, *labels], conditions).items():
        products[item_id] = {
            "item_id": item_id, "title": row.title, "brand": row.brand, "days": 0, "campaigns": [],
            "custom_labels": {f"custom_label_{index}": getattr(row, f"custom_label_{index}")
                              for index in CUSTOM_LABELS if getattr(row, f"custom_label_{index}")},
            **_empty(),
        }
    for item_id, count in db.execute(
        select(model.item_id, func.count(distinct(model.metric_date))).where(*conditions).group_by(model.item_id)
    ).all():
        products[item_id]["days"] = count
    totals = _empty()
    campaigns: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        select(model.item_id, model.campaign_id, *_sums(model))
        .where(*conditions)
        .group_by(model.item_id, model.campaign_id)
    ).all():
        pair = _pair(row.campaign_id, names, row)
        product = products[row.item_id]
        product["campaigns"].append(pair)
        stored_campaign = campaigns.setdefault(row.campaign_id, {
            **{key: pair[key] for key in ("campaign_id", "campaign_name", "campaign_type")},
            "products": 0, **_empty()})
        stored_campaign["products"] += 1
        for bucket in (totals, product, stored_campaign):
            _add(bucket, pair)

    catalog = _catalog_matches(db, set(products))
    matched = [product for product in products.values() if product["item_id"].strip().lower() in catalog]
    matched_cost = sum((product["cost"] for product in matched), Decimal("0"))
    wasted = [product for product in products.values() if _no_conversions(product)]
    ranked = sorted(wasted if no_conversions_only else products.values(),
                    key=lambda item: (-item["cost"], -item["clicks"], item["item_id"]))
    campaign_costs = _campaign_costs(db, days, ("SHOPPING", PERFORMANCE_MAX))

    def product_row(product: dict[str, Any]) -> dict[str, Any]:
        stored = sorted(product["campaigns"], key=lambda item: (-item["cost"], item["campaign_id"]))
        return {
            "item_id": product["item_id"],
            "title": product["title"],
            "brand": product["brand"],
            "custom_labels": product["custom_labels"],
            "days": product["days"],
            "campaign_types": sorted({item["campaign_type"] for item in stored if item["campaign_type"]}),
            **_metrics(product),
            "no_conversions": _no_conversions(product),
            "campaigns": [
                {"campaign_id": item["campaign_id"], "campaign_name": item["campaign_name"],
                 "campaign_type": item["campaign_type"], **_metrics(item)}
                for item in stored
            ],
            "catalog": catalog.get(product["item_id"].strip().lower()),
        }

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "no_conversions_only": no_conversions_only,
        **_window_days(date_from, date_to, days),
        "stored_rows_per_day": PRODUCTS_PER_DAY,
        "totals": {
            "products": len(products),
            **_metrics(totals),
            "no_conversion_products": len(wasted),
            "no_conversion_cost": _money(sum((product["cost"] for product in wasted), Decimal("0"))),
        },
        **_coverage(totals["cost"], campaign_costs, days),
        "catalog_match": {
            "products": len(products),
            "matched": len(matched),
            "match_rate": _rate(len(matched), len(products)),
            "matched_by": {field: sum(1 for match in catalog.values() if match["matched_by"] == field)
                           for field in CATALOG_KEYS},
            "cost": _money(totals["cost"]),
            "matched_cost": _money(matched_cost),
            "cost_match_rate": _rate(matched_cost, totals["cost"]),
        },
        "products": [product_row(product) for product in ranked[:limit]],
        "by_campaign": _campaign_rows(campaigns, campaign_costs, lambda item: {"products": item["products"]}),
        "note": PRODUCTS_NOTE,
    }


# ---------------------------------------------------------------- asset groups


def asset_group_report(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    model = GoogleAdsAssetGroupDailyMetric
    rows = db.execute(
        select(model.metric_date, model.campaign_id, model.campaign_name, model.asset_group_id,
               model.asset_group_name, model.asset_group_status, model.impressions, model.clicks, model.cost,
               model.conversions, model.conversion_value)
        .where(model.metric_date.between(date_from, date_to))
        .order_by(model.metric_date)
    ).all()
    totals = _empty()
    groups: dict[str, dict[str, Any]] = {}
    daily = []
    days: set[date] = set()
    for row in rows:
        days.add(row.metric_date)
        group = groups.setdefault(row.asset_group_id, {"asset_group_id": row.asset_group_id, "dates": set(),
                                                       **_empty()})
        # Rows are read oldest first, so the latest names and status win.
        group.update(asset_group_name=row.asset_group_name, asset_group_status=row.asset_group_status,
                     campaign_id=row.campaign_id, campaign_name=row.campaign_name)
        group["dates"].add(row.metric_date)
        day = _empty()
        for bucket in (totals, group, day):
            _add(bucket, row)
        daily.append({"date": row.metric_date.isoformat(), "asset_group_id": row.asset_group_id, **_metrics(day)})

    campaign_costs = _campaign_costs(db, days, (PERFORMANCE_MAX,))
    group_rows = []
    for group in sorted(groups.values(), key=lambda item: (-item["cost"], item["asset_group_id"])):
        dates = sorted(group["dates"])
        group_rows.append({
            **{field: group[field] for field in ("asset_group_id", "asset_group_name", "asset_group_status",
                                                  "campaign_id", "campaign_name")},
            "first_date": dates[0].isoformat(),
            "last_date": dates[-1].isoformat(),
            "days": len(dates),
            **_metrics(group),
        })
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        **_window_days(date_from, date_to, days),
        "totals": {"asset_groups": len(groups), **_metrics(totals)},
        **_coverage(totals["cost"], campaign_costs, days),
        "asset_groups": group_rows,
        "daily": sorted(daily, key=lambda item: (item["date"], -item["cost"], item["asset_group_id"])),
        "note": ASSET_GROUPS_NOTE,
    }
