from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select

from app.models import (AADEDocument, BankTransaction, CampaignDailyMetric, GA4DailyMetric,
                        MerchantProductMetric, OpenCartOrder, OpenCartOrderProduct, ReviewEvent, SearchConsoleDailyMetric,
                        SyncRun)
from app.services.dashboard_service import _configured_sale_statuses, _opencart_sales_filter
from app.services.supplier_service import product_profitability

AD_SOURCES = ("google_ads", "meta_ads", "tiktok_ads")
CREDIT_TYPES = {"5.1", "5.2", "11.4", "13.31", "14.31"}


def ratio(a, b):
    return round(float(a) / float(b), 4) if b else None


def change(current, previous):
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "percent": None}
    delta = round(current - previous, 4)
    return {"current": current, "previous": previous, "delta": delta,
            "percent": round(delta / abs(previous) * 100, 2) if previous else None}


def compare_rows(current, previous, metrics):
    left, right = {r["key"]: r for r in current}, {r["key"]: r for r in previous}
    result = []
    for key in left.keys() | right.keys():
        a, b = left.get(key, {}), right.get(key, {})
        result.append({"key": key, "name": a.get("name") or b.get("name"),
            "sku": a.get("sku") or b.get("sku"),
            "source": a.get("source") or b.get("source"),
            "state": "both" if a and b else "new_in_period" if a else "absent_in_period",
            "metrics": {m: change(a.get(m, 0), b.get(m, 0)) for m in metrics}})
    return sorted(result, key=lambda r: abs(r["metrics"][metrics[0]]["delta"] or 0), reverse=True)


def source_missing(period, source):
    return next(c["status"] == "missing" for c in period["coverage"] if c["source"] == source)


def comparable_rows(current, baseline, dimension, metrics, source):
    rows = compare_rows(current[dimension], baseline[dimension], metrics)
    for row in rows:
        origin = row["source"] if source == "campaign" else source
        missing_current, missing_baseline = source_missing(current, origin), source_missing(baseline, origin)
        if missing_current or missing_baseline:
            row["state"] = "source_not_loaded"
            row["metrics"] = {m: change(None if missing_current else v["current"],
                                         None if missing_baseline else v["previous"])
                              for m, v in row["metrics"].items()}
    return rows


def covered_days(start, end, runs):
    days = set()
    for a, b in runs:
        if a and b:
            day = max(a, start)
            while day <= min(b, end):
                days.add(day)
                day += timedelta(days=1)
    return len(days)


def coverage(db, start, end):
    expected = (end - start).days + 1
    specs = [(source, CampaignDailyMetric, CampaignDailyMetric.metric_date,
              CampaignDailyMetric.source == source) for source in AD_SOURCES]
    specs += [("ga4", GA4DailyMetric, GA4DailyMetric.metric_date, True),
              ("merchant_center", MerchantProductMetric, MerchantProductMetric.metric_date, True),
              ("search_console", SearchConsoleDailyMetric, SearchConsoleDailyMetric.metric_date, True),
              ("opencart", OpenCartOrder, func.date(OpenCartOrder.date_added), True),
              ("aade", AADEDocument, AADEDocument.issue_date, True),
              ("banks", BankTransaction, BankTransaction.transaction_date, True)]
    result = []
    for source, model, day, condition in specs:
        count, days, first, last = db.execute(select(func.count(), func.count(func.distinct(day)),
            func.min(day), func.max(day)).select_from(model).where(condition, day.between(start, end))).one()
        runs = db.execute(select(SyncRun.date_from, SyncRun.date_to).where(
            SyncRun.provider == source, SyncRun.status == "success",
            SyncRun.sync_type.in_(["manual", "scheduled", "backfill"]),
            SyncRun.date_from <= end, SyncRun.date_to >= start)).all()
        verified = covered_days(start, end, runs)
        result.append({"source": source, "rows": count, "days_with_rows": days, "days_requested": expected,
            "verified_sync_days": verified, "first": str(first) if first else None,
            "last": str(last) if last else None,
            "status": "imported_unverified" if source == "banks" and count else
                      "synced" if verified == expected else "partial" if count else "missing"})
    return result


def _period(db, start, end, with_costs):
    sale_filter = _opencart_sales_filter(db, start, end)
    eur_orders = OpenCartOrder.currency_code.in_(["", "EUR"]) | OpenCartOrder.currency_code.is_(None)
    count, revenue, shipping = db.execute(select(func.count(), func.coalesce(func.sum(OpenCartOrder.total), 0),
        func.coalesce(func.sum(OpenCartOrder.shipping), 0)).where(sale_filter, eur_orders)).one()
    status_rows = db.execute(select(OpenCartOrder.order_status, func.count(), func.sum(OpenCartOrder.total))
        .where(func.date(OpenCartOrder.date_added).between(start, end), eur_orders)
        .group_by(OpenCartOrder.order_status)).all()
    statuses = [{"key": str(r[0] or "Unknown"), "name": r[0] or "Unknown", "orders": r[1],
                 "value": float(r[2] or 0)} for r in status_rows]
    # Campaign IDs, not names, define identity: renames must not appear as new campaigns.
    campaigns = []
    clicks = case((CampaignDailyMetric.source == "meta_ads", CampaignDailyMetric.link_clicks),
                  else_=CampaignDailyMetric.clicks)
    campaign_key = func.coalesce(func.nullif(CampaignDailyMetric.campaign_id, ""), CampaignDailyMetric.campaign_name)
    for row in db.execute(select(CampaignDailyMetric.source, campaign_key,
        func.max(CampaignDailyMetric.campaign_name), func.sum(CampaignDailyMetric.cost),
        func.sum(CampaignDailyMetric.conversion_value), func.sum(CampaignDailyMetric.conversions),
        func.sum(clicks), func.sum(CampaignDailyMetric.impressions))
        .where(CampaignDailyMetric.metric_date.between(start, end), CampaignDailyMetric.source.in_(AD_SOURCES))
        .group_by(CampaignDailyMetric.source, campaign_key)):
        source, key, name, cost, value, conversions, click_count, impressions = row
        campaigns.append({"key": f"{source}:{key}", "source": source, "name": name,
            "cost": float(cost or 0), "value": float(value or 0), "conversions": float(conversions or 0),
            "clicks": click_count or 0, "impressions": impressions or 0, "roas": ratio(value, cost)})
    spend = sum(r["cost"] for r in campaigns)
    merchant = [{"key": r[0], "name": r[1] or r[0], "clicks": int(r[2] or 0), "impressions": int(r[3] or 0)}
        for r in db.execute(select(MerchantProductMetric.item_id, func.max(MerchantProductMetric.title),
            func.sum(MerchantProductMetric.clicks), func.sum(MerchantProductMetric.impressions))
            .where(MerchantProductMetric.metric_date.between(start, end))
            .group_by(MerchantProductMetric.item_id))]
    organic = [{"key": r[0] or "Unknown", "name": r[0] or "Unknown",
                "clicks": int(r[1] or 0), "impressions": int(r[2] or 0)}
        for r in db.execute(select(SearchConsoleDailyMetric.page,
            func.sum(SearchConsoleDailyMetric.clicks), func.sum(SearchConsoleDailyMetric.impressions))
            .where(SearchConsoleDailyMetric.metric_date.between(start, end))
            .group_by(SearchConsoleDailyMetric.page))]
    channels = [{"key": f"{r[0]}:{r[1]}", "name": f"{r[0] or 'Unknown'} / {r[1] or 'Unknown'}",
        "sessions": int(r[2] or 0), "purchases": float(r[3] or 0), "value": float(r[4] or 0)}
        for r in db.execute(select(GA4DailyMetric.channel_group, GA4DailyMetric.source_medium,
            func.sum(GA4DailyMetric.sessions), func.sum(GA4DailyMetric.purchases), func.sum(GA4DailyMetric.purchase_revenue))
            .where(GA4DailyMetric.metric_date.between(start, end))
            .group_by(GA4DailyMetric.channel_group, GA4DailyMetric.source_medium))]
    key = func.coalesce(func.nullif(OpenCartOrderProduct.product_id, ""),
        func.nullif(OpenCartOrderProduct.sku, ""), func.nullif(OpenCartOrderProduct.model, ""),
        OpenCartOrderProduct.name)
    products = [{"key": r[0], "name": r[1], "sku": r[2], "brand": r[3] or "Unknown",
        "category": r[4] or "Unknown", "quantity": int(r[5] or 0), "orders": r[6],
        "value": float(r[7] or 0), "unit_price": ratio(r[7], r[5])}
        for r in db.execute(select(key, func.max(OpenCartOrderProduct.name), func.max(OpenCartOrderProduct.sku),
            func.max(OpenCartOrderProduct.brand), func.max(OpenCartOrderProduct.category),
            func.sum(OpenCartOrderProduct.quantity), func.count(func.distinct(OpenCartOrder.id)),
            func.sum(OpenCartOrderProduct.price * OpenCartOrderProduct.quantity))
            .join(OpenCartOrder, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
            .where(sale_filter, eur_orders).group_by(key))]
    dimensions = {}
    for field in ("brand", "category"):
        groups = {}
        for p in products:
            group = groups.setdefault(p[field], {"key": p[field], "name": p[field], "value": 0, "quantity": 0})
            group["value"] += p["value"]
            group["quantity"] += p["quantity"]
        dimensions[field] = list(groups.values())
    # Full fiscal documents only; book/VAT summary rows overlap and must not be summed.
    fiscal = {"income": 0.0, "expense": 0.0}
    docs = db.execute(select(AADEDocument.document_direction, AADEDocument.invoice_type,
        func.sum(AADEDocument.net_value), func.count()).where(
            AADEDocument.issue_date.between(start, end), AADEDocument.is_cancelled.is_(False),
            func.coalesce(AADEDocument.raw["record_type"].astext, "full_document").in_(["", "full_document"]),
            AADEDocument.currency.in_(["", "EUR"]) | AADEDocument.currency.is_(None))
            .group_by(AADEDocument.document_direction, AADEDocument.invoice_type)).all()
    for direction, invtype, value, _ in docs:
        if direction in fiscal:
            fiscal[direction] += (-abs(float(value or 0)) if str(invtype or "") in CREDIT_TYPES
                                  else float(value or 0))
    bank_rows = db.execute(select(BankTransaction.category, func.sum(BankTransaction.credit),
        func.sum(BankTransaction.debit), func.count()).where(
            BankTransaction.transaction_date.between(start, end),
            BankTransaction.currency.in_(["", "EUR"]) | BankTransaction.currency.is_(None))
            .group_by(BankTransaction.category)).all()
    banks = [{"key": r[0], "name": r[0], "credits": float(r[1] or 0),
              "debits": float(r[2] or 0), "transactions": r[3]} for r in bank_rows]
    data_coverage = coverage(db, start, end)
    metrics = {"order_value": float(revenue), "orders": count, "shipping_charged": float(shipping),
        "ad_spend": spend, "blended_ratio": ratio(revenue, spend), "average_order": ratio(revenue, count),
        "ad_cost_per_order": ratio(spend, count),
        "ga4_value": sum(r["value"] for r in channels), "ga4_purchases": sum(r["purchases"] for r in channels),
        "aade_income_net": fiscal["income"], "aade_expense_net": fiscal["expense"],
        "merchant_clicks": sum(r["clicks"] for r in merchant),
        "organic_clicks": sum(r["clicks"] for r in organic),
        "bank_credits": sum(r["credits"] for r in banks), "bank_debits": sum(r["debits"] for r in banks)}
    # Unknown is not zero. Source coverage remains visible even when rows exist.
    present = {c["source"]: c["status"] != "missing" for c in data_coverage}
    if not any(present[s] for s in AD_SOURCES):
        for name in ("ad_spend", "blended_ratio", "ad_cost_per_order"):
            metrics[name] = None
    for source, names in {"opencart": ("order_value", "orders", "shipping_charged", "average_order"),
                          "ga4": ("ga4_value", "ga4_purchases"),
                          "aade": ("aade_income_net", "aade_expense_net"),
                          "merchant_center": ("merchant_clicks",),
                          "search_console": ("organic_clicks",),
                          "banks": ("bank_credits", "bank_debits")}.items():
        if not present[source]:
            for name in names:
                metrics[name] = None
    if not present["opencart"]:
        metrics["blended_ratio"] = metrics["ad_cost_per_order"] = None
    if not docs and any(c["source"] == "aade" and c["rows"] for c in data_coverage):
        metrics["aade_income_net"] = metrics["aade_expense_net"] = None
    costs = None
    if with_costs:
        rows = product_profitability(db, start, end, _configured_sale_statuses(db), include_later_invoices=True)
        complete = [r for r in rows if r["cogs"] is not None and r["net_sales"] is not None]
        costs = {"products": len(rows), "fully_costed_products": len(complete),
            "covered_net_sales": sum(r["net_sales"] for r in complete),
            "covered_cogs": sum(r["cogs"] for r in complete),
            "covered_gross_profit": sum(r["gross_profit"] for r in complete),
            "basis": "Estimated invoice cost on covered products only; not business net profit."}
    return {"date_from": str(start), "date_to": str(end), "days": (end-start).days+1,
        "metrics": metrics, "campaigns": campaigns, "channels": channels, "products": products,
        "brands": dimensions["brand"], "categories": dimensions["category"], "banks": banks,
        "statuses": statuses, "merchant_products": merchant, "organic_pages": organic,
        "coverage": data_coverage, "costs": costs}


def serialize_event(event):
    return {"id": str(event.id), "source": event.source, "occurred_at": event.occurred_at.isoformat(),
        "evidence_type": event.evidence_type, "actor": event.actor, "object_id": event.object_id,
        "title": event.title, "detail": event.detail, "reference_url": event.reference_url,
        "payload": event.payload}


def build_review(db, start, end, baseline_start, baseline_end, *, with_costs=False):
    for a, b in ((start, end), (baseline_start, baseline_end)):
        if a > b or (b-a).days > 365:
            raise ValueError("Each comparison period must contain between 1 and 366 days.")
    current, baseline = _period(db, start, end, with_costs), _period(db, baseline_start, baseline_end, with_costs)
    metrics = {k: change(v, baseline["metrics"][k]) for k, v in current["metrics"].items()}
    comparisons = {
        "campaigns": comparable_rows(current, baseline, "campaigns",
                                 ["value", "cost", "conversions", "roas", "clicks"], "campaign"),
        "channels": comparable_rows(current, baseline, "channels", ["value", "sessions", "purchases"], "ga4"),
        "products": comparable_rows(current, baseline, "products", ["value", "quantity", "orders", "unit_price"], "opencart"),
        "brands": comparable_rows(current, baseline, "brands", ["value", "quantity"], "opencart"),
        "categories": comparable_rows(current, baseline, "categories", ["value", "quantity"], "opencart"),
        "statuses": comparable_rows(current, baseline, "statuses", ["value", "orders"], "opencart"),
        "banks": comparable_rows(current, baseline, "banks", ["credits", "debits", "transactions"], "banks"),
        "merchant_products": comparable_rows(current, baseline, "merchant_products", ["clicks", "impressions"], "merchant_center"),
        "organic_pages": comparable_rows(current, baseline, "organic_pages", ["clicks", "impressions"], "search_console"),
    }
    findings = []
    def finding(severity, title, detail):
        findings.append({"severity": severity, "title": title, "detail": detail})
    if current["days"] != baseline["days"]:
        finding("warning", "Unequal period lengths", "Use per-day figures as well as totals.")
    if max(start, baseline_start) <= min(end, baseline_end):
        finding("warning", "Overlapping comparison periods", "Some of the same days occur in both periods.")
    for label, period in (("Current", current), ("Baseline", baseline)):
        gaps = [r["source"] for r in period["coverage"] if r["status"] != "synced"]
        if gaps:
            finding("warning", f"{label}: incomplete or unverified coverage", ", ".join(gaps))
    revenue_change, orders_change = metrics["order_value"]["percent"], metrics["orders"]["percent"]
    if revenue_change is not None and orders_change is not None:
        finding("observation", "Order growth decomposition",
            f"Order value {revenue_change:+.1f}%; orders {orders_change:+.1f}%; "
            f"average order {metrics['average_order']['percent'] or 0:+.1f}%. This is association, not causation.")
    for row in comparisons["campaigns"]:
        cost, roas = row["metrics"]["cost"]["current"], row["metrics"]["roas"]["current"]
        if cost is not None and cost >= 50 and roas is not None and roas < 1:
            finding("warning", row["name"], f"Attributed value/spend is {roas:.2f} on {cost:.2f} EUR spend. "
                    "Verify conversion lag, goals and margin before any campaign decision.")
    source_totals = []
    for source in AD_SOURCES:
        a, b = [r for r in current["campaigns"] if r["source"] == source], [r for r in baseline["campaigns"] if r["source"] == source]
        source_totals.append({"key": source, "name": source,
            "cost": change(None if source_missing(current, source) else sum(r["cost"] for r in a),
                           None if source_missing(baseline, source) else sum(r["cost"] for r in b)),
            "value": change(None if source_missing(current, source) else sum(r["value"] for r in a),
                            None if source_missing(baseline, source) else sum(r["value"] for r in b)),
            "roas": change(ratio(sum(r["value"] for r in a), sum(r["cost"] for r in a)),
                           ratio(sum(r["value"] for r in b), sum(r["cost"] for r in b)))})
    for row in source_totals:
        if row["cost"]["percent"] is not None and row["roas"]["percent"] is not None:
            finding("observation", f"{row['name']}: spend versus efficiency",
                f"Spend {row['cost']['percent']:+.1f}%; attributed value/spend "
                f"{row['roas']['percent']:+.1f}%. Attribution is not incremental business revenue.")
    for dimension in ("products", "categories"):
        ranked = [r for r in comparisons[dimension] if r["metrics"]["value"]["delta"] is not None]
        for row in sorted(ranked, key=lambda r: abs(r["metrics"]["value"]["delta"]), reverse=True)[:3]:
            delta = row["metrics"]["value"]["delta"]
            if delta:
                finding("observation", f"{dimension}: {row['name']}",
                    f"Recorded product-line value changed by {delta:+.2f} EUR. "
                    "Check quantity, unit price and order status; this is a contribution, not a causal claim.")
    events = db.scalars(select(ReviewEvent).where(
        func.date(func.timezone("Europe/Athens", ReviewEvent.occurred_at)).between(start, end) |
        func.date(func.timezone("Europe/Athens", ReviewEvent.occurred_at)).between(baseline_start, baseline_end))
        .order_by(ReviewEvent.occurred_at.desc()).limit(501)).all()
    # Do not send/store the full raw dimensions twice alongside their comparisons.
    summary_keys = ("date_from", "date_to", "days", "metrics", "coverage", "costs")
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
        "current": {k: current[k] for k in summary_keys},
        "baseline": {k: baseline[k] for k in summary_keys},
        "metrics": metrics, "comparisons": comparisons, "sources": source_totals,
        "findings": findings, "events": [serialize_event(e) for e in events[:500]], "events_truncated": len(events) > 500,
        "limitations": [
            "Orders include configured sale statuses, including unfulfilled/unpaid orders. Not confirmed receipts.",
            "Order values include tax/shipping; product values are recorded unit price times quantity.",
            "Platform attribution overlaps. Google conversions may include non-purchase goals. Do not add channel revenue.",
            "Fiscal totals use full, non-cancelled EUR documents, with credit notes deducted; book-only data is excluded.",
            "Bank credits/debits include transfers and other flows. They are not additional revenue or business profit.",
            "Current product identity/status and later invoices can revise historical reports; saved snapshots are immutable.",
            "Recent conversions may mature; seasonality, weekday mix and stock changes can explain differences.",
            "Merchant clicks are performance, not approval/stock history. Search Console query rows may omit anonymized traffic.",
            "Coverage means the date range was requested successfully, not that an external API exposed every event or document.",
            "Shoply historical segmentation requires its own export/logs. Email claims are not API-confirmed changes.",
        ]}
