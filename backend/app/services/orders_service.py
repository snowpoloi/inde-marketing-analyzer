from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import BankTransaction, IntegrationSetting, OpenCartOrder, OpenCartOrderChange
from app.services.bank_service import match_bank_deposits_for_orders
from app.services.parsing import as_decimal, dec_to_float

PAYMENT_TOLERANCE = Decimal("0.05")
UNKNOWN_STATUS = "Unknown"
REFUND_STATUS_NAMES = ("Επιστράφηκε το ποσό", "Επιστροφή Χρημάτων")


def order_analytics_options(db: Session) -> dict[str, Any]:
    status_expr = func.coalesce(func.nullif(func.trim(OpenCartOrder.order_status), ""), UNKNOWN_STATUS)
    status_rows = db.execute(
        select(
            status_expr.label("status"),
            func.count(OpenCartOrder.id).label("orders"),
        )
        .group_by(status_expr)
        .order_by(func.count(OpenCartOrder.id).desc(), status_expr)
    ).all()
    statuses_by_key = {
        _status_key(row.status): {"name": str(row.status), "orders": int(row.orders or 0)}
        for row in status_rows
    }
    history_rows = db.execute(
        select(OpenCartOrderChange.old_value, OpenCartOrderChange.new_value)
        .where(OpenCartOrderChange.field_name == "order_status")
    ).all()
    for history_row in history_rows:
        for value in (history_row.old_value, history_row.new_value):
            _add_status_option(statuses_by_key, value)
    for name in _configured_status_names(db):
        _add_status_option(statuses_by_key, name)
    for name in REFUND_STATUS_NAMES:
        _add_status_option(statuses_by_key, name)
    saved_defaults = _configured_analytics_defaults(db)
    for field in ("statuses", "aging_statuses", "processed_statuses", "completed_statuses", "cancelled_statuses"):
        saved_names = saved_defaults.get(field)
        for name in saved_names if isinstance(saved_names, list) else []:
            _add_status_option(statuses_by_key, name)

    statuses = sorted(
        statuses_by_key.values(),
        key=lambda row: (-row["orders"], row["name"].casefold()),
    )
    names = [row["name"] for row in statuses]
    names_by_key = {_status_key(name): name for name in names}

    cancelled = [name for name in names if _looks_cancelled(name)]
    cancelled_keys = {_status_key(name) for name in cancelled}
    completed = [name for name in names if _looks_completed(name) and _status_key(name) not in cancelled_keys]
    if not completed:
        configured = _configured_completed_statuses(db)
        completed = [names_by_key[key] for key in configured if key in names_by_key and key not in cancelled_keys]

    completed_keys = {_status_key(name) for name in completed}
    fallback_aging = [name for name in names if _status_key(name) not in cancelled_keys | completed_keys]
    defaults = _normalize_analytics_defaults(
        saved_defaults,
        statuses=names,
        aging_statuses=fallback_aging,
        processed_statuses=fallback_aging,
        completed_statuses=completed,
        cancelled_statuses=cancelled,
    )

    return {
        "statuses": statuses,
        "aging_statuses": fallback_aging,
        "processed_statuses": fallback_aging,
        "completed_statuses": completed,
        "cancelled_statuses": cancelled,
        "defaults": defaults,
    }


def save_order_analytics_defaults(
    db: Session,
    statuses: list[str],
    aging_statuses: list[str],
    processed_statuses: list[str],
    completed_statuses: list[str],
    cancelled_statuses: list[str],
    group_by: str,
    stale_days: int,
) -> dict[str, Any]:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "opencart"))
    if integration is None:
        integration = IntegrationSetting(
            provider="opencart",
            display_name="OpenCart",
            is_enabled=False,
            config={},
        )
        db.add(integration)

    defaults = _normalize_analytics_defaults(
        {
            "statuses": statuses,
            "aging_statuses": aging_statuses,
            "processed_statuses": processed_statuses,
            "completed_statuses": completed_statuses,
            "cancelled_statuses": cancelled_statuses,
            "group_by": group_by,
            "stale_days": stale_days,
        },
        statuses=[],
        aging_statuses=[],
        processed_statuses=[],
        completed_statuses=[],
        cancelled_statuses=[],
    )
    config = dict(integration.config or {})
    config["order_analytics_defaults"] = defaults
    integration.config = config
    db.commit()
    return order_analytics_options(db)


def orders_analytics(
    db: Session,
    periods: list[dict[str, Any]],
    statuses: list[str],
    aging_statuses: list[str],
    processed_statuses: list[str],
    completed_statuses: list[str],
    cancelled_statuses: list[str],
    group_by: str,
    stale_days: int,
) -> dict[str, Any]:
    selected_keys = {_status_key(value) for value in statuses if str(value).strip()}
    aging_keys = {_status_key(value) for value in aging_statuses if str(value).strip()}
    processed_keys = {_status_key(value) for value in processed_statuses if str(value).strip()}
    completed_keys = {_status_key(value) for value in completed_statuses if str(value).strip()}
    cancelled_keys = {_status_key(value) for value in cancelled_statuses if str(value).strip()}
    completed_keys -= cancelled_keys
    processed_keys -= completed_keys | cancelled_keys
    aging_keys -= completed_keys | cancelled_keys

    earliest = min(period["date_from"] for period in periods)
    latest = max(period["date_to"] for period in periods)
    period_orders = db.scalars(
        select(OpenCartOrder)
        .where(func.date(OpenCartOrder.date_added).between(earliest, latest))
        .order_by(OpenCartOrder.date_added)
    ).all()

    period_results = [
        _period_analytics(
            period,
            period_orders,
            selected_keys,
            processed_keys,
            completed_keys,
            cancelled_keys,
            group_by,
        )
        for period in periods
    ]
    status_aging, stale_orders, stale_total = _status_aging(db, aging_keys, stale_days)
    primary = period_results[0]

    return {
        "summary": {
            "orders": primary["orders"],
            "processed": primary["processed"],
            "completed": primary["completed"],
            "cancelled": primary["cancelled"],
            "open": primary["open"],
            "other_open": primary["other_open"],
            "processed_rate": primary["processed_rate"],
            "completion_rate": primary["completion_rate"],
            "stage_totals": primary["stage_totals"],
            "stale_orders": stale_total,
            "primary_period": primary["label"],
        },
        "group_by": group_by,
        "stale_days": stale_days,
        "periods": period_results,
        "status_aging": status_aging,
        "stale_orders": stale_orders,
        "stale_orders_total": stale_total,
    }


def _period_analytics(
    period: dict[str, Any],
    orders: list[OpenCartOrder],
    selected_keys: set[str],
    processed_keys: set[str],
    completed_keys: set[str],
    cancelled_keys: set[str],
    group_by: str,
) -> dict[str, Any]:
    start: date = period["date_from"]
    end: date = period["date_to"]
    rows = [order for order in orders if start <= _as_date(order.date_added) <= end]
    processed_rows: list[OpenCartOrder] = []
    completed_rows: list[OpenCartOrder] = []
    cancelled_rows: list[OpenCartOrder] = []
    processed = 0
    completed = 0
    cancelled = 0
    status_counts: dict[str, int] = defaultdict(int)
    series = {
        bucket: {"bucket": bucket, "orders": 0, "processed": 0, "completed": 0, "cancelled": 0}
        for bucket in _period_buckets(start, end, group_by)
    }

    for order in rows:
        status = order.order_status or UNKNOWN_STATUS
        status_key = _status_key(status)
        bucket = _bucket_key(_as_date(order.date_added), group_by)
        point = series[bucket]
        point["orders"] += 1
        if status_key in cancelled_keys:
            cancelled += 1
            cancelled_rows.append(order)
            point["cancelled"] += 1
        elif status_key in completed_keys:
            completed += 1
            completed_rows.append(order)
            point["completed"] += 1
        elif status_key in processed_keys:
            processed += 1
            processed_rows.append(order)
            point["processed"] += 1
        if status_key in selected_keys:
            status_counts[status] += 1

    received_totals = _order_stage_totals(rows)
    stage_totals = {
        "received": received_totals,
        "processed": _order_stage_totals(processed_rows),
        "completed": _order_stage_totals(completed_rows),
        "cancelled": _order_stage_totals(cancelled_rows),
    }
    total = received_totals["orders"]
    open_orders = max(total - completed - cancelled, 0)
    return {
        "key": period["key"],
        "label": period["label"],
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        **received_totals,
        "processed": processed,
        "completed": completed,
        "cancelled": cancelled,
        "open": open_orders,
        "other_open": max(open_orders - processed, 0),
        "processed_rate": round((processed / total * 100) if total else 0, 2),
        "completion_rate": round((completed / total * 100) if total else 0, 2),
        "stage_totals": stage_totals,
        "status_counts": [
            {"status": status, "orders": count}
            for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
        ],
        "series": list(series.values()),
    }


def _order_stage_totals(orders: list[OpenCartOrder]) -> dict[str, Any]:
    count = len(orders)
    sub_total = sum((order.sub_total or Decimal("0") for order in orders), Decimal("0"))
    shipping = sum((order.shipping or Decimal("0") for order in orders), Decimal("0"))
    coupon = sum((_coupon_amount(order) for order in orders), Decimal("0"))
    taxes = sum((order.tax or Decimal("0") for order in orders), Decimal("0"))
    total_value = sum((order.total or Decimal("0") for order in orders), Decimal("0"))
    return {
        "orders": count,
        "customers": len({_customer_key(order) for order in orders}),
        "sub_total": dec_to_float(sub_total),
        "shipping": dec_to_float(shipping),
        "coupon": dec_to_float(coupon),
        "taxes": dec_to_float(taxes),
        "total_value": dec_to_float(total_value),
        "average_order_value": dec_to_float(total_value / count) if count else 0,
    }


def _status_aging(
    db: Session,
    selected_keys: set[str],
    stale_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if not selected_keys:
        return [], [], 0

    latest_change = (
        select(
            OpenCartOrderChange.order_pk.label("order_pk"),
            func.max(
                func.coalesce(OpenCartOrderChange.source_modified_at, OpenCartOrderChange.detected_at)
            ).label("status_since"),
        )
        .where(OpenCartOrderChange.field_name == "order_status")
        .group_by(OpenCartOrderChange.order_pk)
        .subquery()
    )
    rows = db.execute(
        select(OpenCartOrder, latest_change.c.status_since)
        .outerjoin(latest_change, latest_change.c.order_pk == OpenCartOrder.id)
        .order_by(OpenCartOrder.date_added.desc())
    ).all()

    now = datetime.now(timezone.utc)
    aging: dict[str, dict[str, Any]] = {}
    order_rows: list[dict[str, Any]] = []
    for order, tracked_since in rows:
        status = order.order_status or UNKNOWN_STATUS
        if _status_key(status) not in selected_keys:
            continue
        status_since = tracked_since or order.date_modified or order.date_added
        status_since = _as_utc(status_since)
        days = max((now.date() - status_since.date()).days, 0)
        source = "tracked" if tracked_since else "estimated"
        bucket = aging.setdefault(
            status,
            {"status": status, "orders": 0, "stale_orders": 0, "days_total": 0, "max_days": 0},
        )
        bucket["orders"] += 1
        bucket["days_total"] += days
        bucket["max_days"] = max(bucket["max_days"], days)
        if days >= stale_days:
            bucket["stale_orders"] += 1
            order_rows.append(
                {
                    "order_id": order.order_id,
                    "date_added": order.date_added.isoformat(),
                    "status": status,
                    "status_since": status_since.isoformat(),
                    "days_in_status": days,
                    "age_source": source,
                    "total": dec_to_float(order.total),
                    "payment_method": order.payment_method,
                    "shipping_method": order.shipping_method or order.shipping_title,
                }
            )

    status_rows = [
        {
            "status": row["status"],
            "orders": row["orders"],
            "stale_orders": row["stale_orders"],
            "average_days": round(row["days_total"] / row["orders"], 1) if row["orders"] else 0,
            "max_days": row["max_days"],
        }
        for row in aging.values()
    ]
    status_rows.sort(key=lambda row: (-row["stale_orders"], -row["max_days"], row["status"].casefold()))
    order_rows.sort(key=lambda row: (-row["days_in_status"], row["status"].casefold(), row["order_id"]))
    return status_rows, order_rows[:500], len(order_rows)


def _configured_completed_statuses(db: Session) -> list[str]:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "opencart"))
    rules = ((integration.config if integration else {}) or {}).get("order_status_rules") or []
    return [
        _status_key(rule.get("name"))
        for rule in rules
        if isinstance(rule, dict) and rule.get("counts_as_sale") and str(rule.get("name") or "").strip()
    ]


def _configured_status_names(db: Session) -> list[str]:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "opencart"))
    rules = ((integration.config if integration else {}) or {}).get("order_status_rules") or []
    return [
        str(rule.get("name")).strip()
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("name") or "").strip()
    ]


def _configured_analytics_defaults(db: Session) -> dict[str, Any]:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "opencart"))
    defaults = ((integration.config if integration else {}) or {}).get("order_analytics_defaults")
    return defaults if isinstance(defaults, dict) else {}


def _normalize_analytics_defaults(
    values: dict[str, Any],
    *,
    statuses: list[str],
    aging_statuses: list[str],
    processed_statuses: list[str],
    completed_statuses: list[str],
    cancelled_statuses: list[str],
) -> dict[str, Any]:
    displayed = _unique_status_names(values.get("statuses"), statuses)
    cancelled = _unique_status_names(values.get("cancelled_statuses"), cancelled_statuses)
    cancelled_keys = {_status_key(name) for name in cancelled}
    completed = [
        name
        for name in _unique_status_names(values.get("completed_statuses"), completed_statuses)
        if _status_key(name) not in cancelled_keys
    ]
    terminal_keys = cancelled_keys | {_status_key(name) for name in completed}
    processed = [
        name
        for name in _unique_status_names(values.get("processed_statuses"), processed_statuses)
        if _status_key(name) not in terminal_keys
    ]
    aging = [
        name
        for name in _unique_status_names(values.get("aging_statuses"), aging_statuses)
        if _status_key(name) not in terminal_keys
    ]
    group_by = values.get("group_by")
    stale_days = values.get("stale_days")
    return {
        "statuses": displayed,
        "aging_statuses": aging,
        "processed_statuses": processed,
        "completed_statuses": completed,
        "cancelled_statuses": cancelled,
        "group_by": group_by if group_by in {"day", "month"} else "day",
        "stale_days": min(max(int(stale_days), 0), 3650) if isinstance(stale_days, int) else 3,
    }


def _unique_status_names(values: Any, fallback: list[str]) -> list[str]:
    source = values if isinstance(values, list) else fallback
    names: list[str] = []
    seen: set[str] = set()
    for value in source:
        name = str(value or "").strip()
        key = _status_key(name)
        if not key or key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def _add_status_option(statuses: dict[str, dict[str, Any]], value: Any) -> None:
    name = str(value or "").strip()
    key = _status_key(name)
    if key and key not in statuses:
        statuses[key] = {"name": name, "orders": 0}


def _customer_key(order: OpenCartOrder) -> str:
    customer_id = str(order.customer_id or "").strip()
    if customer_id and customer_id != "0":
        return f"id:{customer_id}"
    raw = order.raw if isinstance(order.raw, dict) else {}
    for key in ("email", "customer_email", "payment_email"):
        value = str(raw.get(key) or "").strip().casefold()
        if value:
            return f"email:{value}"
    return f"order:{order.order_id}"


def _coupon_amount(order: OpenCartOrder) -> Decimal:
    raw = order.raw if isinstance(order.raw, dict) else {}
    for key in ("coupon_value", "coupon_total", "coupon_amount", "discount_value", "discount_total"):
        if raw.get(key) not in (None, ""):
            return _negative_discount(raw.get(key))

    for totals_key in ("totals", "order_totals"):
        totals = raw.get(totals_key)
        if not isinstance(totals, list):
            continue
        amount = Decimal("0")
        found = False
        for item in totals:
            if not isinstance(item, dict):
                continue
            code = _status_key(item.get("code"))
            title = _status_key(item.get("title") or item.get("name"))
            if code != "coupon" and "coupon" not in title and "κουπον" not in title:
                continue
            value = next(
                (item.get(key) for key in ("value", "amount", "total") if item.get(key) not in (None, "")),
                0,
            )
            amount += _negative_discount(value)
            found = True
        if found:
            return amount
    return Decimal("0")


def _negative_discount(value: Any) -> Decimal:
    amount = as_decimal(value)
    return amount if amount <= 0 else -amount


def _status_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def _looks_cancelled(status: str) -> bool:
    value = _status_key(status)
    return any(token in value for token in ("cancel", "ακυρ", "refund", "επιστροφ", "void"))


def _looks_completed(status: str) -> bool:
    value = _status_key(status)
    return any(
        token in value
        for token in ("complete", "completed", "delivered", "shipped", "ολοκληρ", "παραδοθ", "παρεληφ", "αποσταλ")
    )


def _as_date(value: datetime) -> date:
    return value.date()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bucket_key(value: date, group_by: str) -> str:
    return value.isoformat() if group_by == "day" else value.strftime("%Y-%m")


def _period_buckets(start: date, end: date, group_by: str) -> list[str]:
    buckets: list[str] = []
    cursor = start
    if group_by == "day":
        while cursor <= end:
            buckets.append(cursor.isoformat())
            cursor += timedelta(days=1)
        return buckets

    cursor = cursor.replace(day=1)
    end_month = end.replace(day=1)
    while cursor <= end_month:
        buckets.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (1 if cursor.month == 12 else 0),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return buckets


def orders_overview(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    orders = db.scalars(
        select(OpenCartOrder)
        .options(selectinload(OpenCartOrder.products))
        .where(func.date(OpenCartOrder.date_added).between(date_from, date_to))
        .order_by(OpenCartOrder.date_added.desc())
    ).all()

    deposits = db.scalars(
        select(BankTransaction)
        .where(
            BankTransaction.transaction_date >= date_from - timedelta(days=14),
            BankTransaction.transaction_date <= date_to + timedelta(days=14),
            BankTransaction.amount > 0,
        )
        .order_by(BankTransaction.transaction_date.desc(), BankTransaction.created_at.desc())
    ).all()

    deposit_matches = match_bank_deposits_for_orders(deposits, orders)
    payments_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for deposit in deposits:
        match = deposit_matches.get(deposit.id)
        if not match:
            continue
        payments_by_order[match["order_id"]].append(_payment_row(deposit, match))

    order_rows = [_order_row(order, payments_by_order.get(order.order_id, [])) for order in orders]
    supplier_totals, supplier_products = _supplier_rows(orders)
    summary = _summary(order_rows, supplier_totals)
    return {
        "summary": summary,
        "orders": order_rows,
        "supplier_sales": supplier_totals,
        "supplier_products": supplier_products,
    }


def _payment_row(deposit: BankTransaction, match: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(deposit.id),
        "transaction_date": deposit.transaction_date.isoformat(),
        "bank_name": deposit.bank_name,
        "amount": dec_to_float(deposit.amount),
        "description": deposit.description,
        "reference": deposit.reference,
        "coverage": match["payment_coverage"],
        "match_reason": match["match_reason"],
    }


def _order_row(order: OpenCartOrder, payments: list[dict[str, Any]]) -> dict[str, Any]:
    total = Decimal(str(order.total or 0))
    paid_amount = sum((Decimal(str(payment["amount"] or 0)) for payment in payments), Decimal("0"))
    balance = total - paid_amount
    product_quantity = sum((product.quantity or 0) for product in order.products)
    status = _payment_status(total, paid_amount)
    return {
        "order_id": order.order_id,
        "date_added": order.date_added.isoformat(),
        "order_status": order.order_status,
        "payment_method": order.payment_method,
        "shipping_method": order.shipping_method or order.shipping_title,
        "products_total": dec_to_float(order.sub_total),
        "shipping_total": dec_to_float(order.shipping),
        "tax_total": dec_to_float(order.tax),
        "order_total": dec_to_float(total),
        "paid_amount": dec_to_float(paid_amount),
        "balance_due": dec_to_float(balance if balance > PAYMENT_TOLERANCE else Decimal("0")),
        "payment_status": status,
        "product_quantity": product_quantity,
        "product_lines": len(order.products),
        "payments": payments,
    }


def _payment_status(total: Decimal, paid_amount: Decimal) -> str:
    if paid_amount <= PAYMENT_TOLERANCE:
        return "unpaid"
    gap = paid_amount - total
    if abs(gap) <= PAYMENT_TOLERANCE:
        return "paid"
    if gap > PAYMENT_TOLERANCE:
        return "overpaid"
    return "partial"


def _supplier_rows(orders: list[OpenCartOrder]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supplier_totals: dict[str, dict[str, Any]] = {}
    supplier_products: dict[tuple[str, str, str], dict[str, Any]] = {}

    for order in orders:
        for product in order.products:
            supplier = product.manufacturer or product.brand or "Unknown"
            quantity = product.quantity or 0
            revenue = Decimal(str(product.price or 0)) * Decimal(quantity)

            supplier_bucket = supplier_totals.setdefault(
                supplier,
                {
                    "supplier": supplier,
                    "orders": set(),
                    "product_lines": 0,
                    "quantity": 0,
                    "revenue": Decimal("0"),
                },
            )
            supplier_bucket["orders"].add(order.order_id)
            supplier_bucket["product_lines"] += 1
            supplier_bucket["quantity"] += quantity
            supplier_bucket["revenue"] += revenue

            product_key = (supplier, product.sku or product.model or product.product_id or product.name, product.name)
            product_bucket = supplier_products.setdefault(
                product_key,
                {
                    "supplier": supplier,
                    "sku": product.sku,
                    "model": product.model,
                    "product_id": product.product_id,
                    "product_name": product.name,
                    "orders": set(),
                    "quantity": 0,
                    "revenue": Decimal("0"),
                },
            )
            product_bucket["orders"].add(order.order_id)
            product_bucket["quantity"] += quantity
            product_bucket["revenue"] += revenue

    supplier_rows = [
        {
            "supplier": row["supplier"],
            "orders": len(row["orders"]),
            "product_lines": row["product_lines"],
            "quantity": row["quantity"],
            "revenue": dec_to_float(row["revenue"]),
        }
        for row in supplier_totals.values()
    ]
    product_rows = [
        {
            "supplier": row["supplier"],
            "sku": row["sku"],
            "model": row["model"],
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "orders": len(row["orders"]),
            "quantity": row["quantity"],
            "revenue": dec_to_float(row["revenue"]),
        }
        for row in supplier_products.values()
    ]
    supplier_rows.sort(key=lambda row: row["revenue"], reverse=True)
    product_rows.sort(key=lambda row: row["revenue"], reverse=True)
    return supplier_rows, product_rows[:250]


def _summary(order_rows: list[dict[str, Any]], supplier_rows: list[dict[str, Any]]) -> dict[str, Any]:
    paid_orders = sum(1 for order in order_rows if order["payment_status"] == "paid")
    partial_orders = sum(1 for order in order_rows if order["payment_status"] == "partial")
    unpaid_orders = sum(1 for order in order_rows if order["payment_status"] == "unpaid")
    overpaid_orders = sum(1 for order in order_rows if order["payment_status"] == "overpaid")
    return {
        "orders": len(order_rows),
        "paid_orders": paid_orders,
        "partial_orders": partial_orders,
        "unpaid_orders": unpaid_orders,
        "overpaid_orders": overpaid_orders,
        "products_total": sum(order["products_total"] for order in order_rows),
        "shipping_total": sum(order["shipping_total"] for order in order_rows),
        "order_total": sum(order["order_total"] for order in order_rows),
        "paid_amount": sum(order["paid_amount"] for order in order_rows),
        "balance_due": sum(order["balance_due"] for order in order_rows),
        "product_quantity": sum(order["product_quantity"] for order in order_rows),
        "suppliers": len(supplier_rows),
    }
