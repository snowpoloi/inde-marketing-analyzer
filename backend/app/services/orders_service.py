from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import BankTransaction, OpenCartOrder
from app.services.bank_service import match_bank_deposits_for_orders
from app.services.parsing import dec_to_float

PAYMENT_TOLERANCE = Decimal("0.05")


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
