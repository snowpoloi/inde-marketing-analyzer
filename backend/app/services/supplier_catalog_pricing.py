"""Catalog price comparison, never a substitute for order-level realized profit."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (AADEDocument, ProductCatalog, Supplier, SupplierDocument,
                        SupplierDocumentLine, SupplierProductCost, SupplierProductMap)
from app.services.supplier_costing import decimal_value, margin_metrics, money
from app.services.supplier_aade_costs import validated_cost_rows


def catalog_sale_price(product: ProductCatalog | None) -> dict:
    if product is None:
        return {"inde_price": None, "inde_price_net": None, "inde_price_basis": "unmatched"}
    raw = product.raw or {}
    fields = {**(raw.get("raw_fields") or {}), **raw}
    price = product.price if raw.get("price", product.price) not in (None, "") else None
    if price is not None and (not price.is_finite() or price < 0):
        price = None
    net = decimal_value(fields.get("price_net"), None)
    gross = decimal_value(fields.get("price_gross"), None)
    basis = "unknown"
    if net is not None and net >= 0:
        price, basis = (gross, "gross") if gross is not None and gross >= 0 else (net, "net")
    elif gross is not None and gross >= 0:
        price = gross
        rate = decimal_value(fields.get("vat_rate"), None)
        net = gross / (1 + rate / 100) if rate is not None and 0 <= rate <= 100 else None
        basis = "gross"
    else:
        net = None
        declared = fields.get("prices_include_vat")
        if str(declared).lower() in {"false", "0", "no"}:
            net, basis = price, "net"
        elif str(declared).lower() in {"true", "1", "yes"}:
            basis = "gross"
            rate = decimal_value(fields.get("vat_rate"), None)
            if price is not None and rate is not None and 0 <= rate <= 100:
                net = price / (1 + rate / 100)
    if fields.get("currency", "EUR") != "EUR":
        net = None
    return {"inde_price": price, "inde_price_net": money(net) if net is not None else None,
            "inde_price_basis": basis}


def latest_aade_costs(db, product_ids, supplier_codes) -> dict:
    if not product_ids:
        return {}
    # Only costs explicitly sourced from AADE lines qualify, not Gmail/imported
    # invoices that happen to reconcile to the same AADE document total.
    eligible = select(
        SupplierProductCost.id.label("cost_id"),
        func.dense_rank().over(partition_by=(SupplierProductCost.supplier_id, SupplierProductCost.product_catalog_id),
                               order_by=SupplierProductCost.purchase_date.desc()).label("recency"),
    ).join(Supplier, Supplier.id == SupplierProductCost.supplier_id).join(
        SupplierProductMap, SupplierProductMap.id == SupplierProductCost.supplier_product_map_id).join(
        SupplierDocumentLine, SupplierDocumentLine.id == SupplierProductCost.source_line_id).join(
        SupplierDocument, SupplierDocument.id == SupplierDocumentLine.document_id).join(
        AADEDocument, AADEDocument.id == SupplierDocument.aade_document_id).where(
        SupplierProductCost.product_catalog_id.in_(product_ids), Supplier.code.in_(supplier_codes),
        SupplierProductCost.source_type == "aade_invoice", SupplierProductCost.status == "active",
        SupplierProductCost.currency == "EUR", SupplierProductCost.net_unit_cost >= 0,
        SupplierProductCost.quantity > 0, SupplierProductCost.source_confidence >= Decimal("0.99"),
        SupplierProductCost.purchase_date <= date.today(), SupplierProductMap.verified.is_(True),
        SupplierProductMap.status == "matched", SupplierProductMap.supplier_id == Supplier.id,
        SupplierProductMap.product_catalog_id == SupplierProductCost.product_catalog_id,
        SupplierDocumentLine.supplier_product_map_id == SupplierProductMap.id,
        SupplierDocumentLine.line_type == "product", SupplierDocumentLine.quantity > 0,
        SupplierProductMap.conversion_factor > 0, SupplierDocument.supplier_id == Supplier.id,
        SupplierDocument.document_type == "invoice", SupplierDocument.currency == "EUR",
        SupplierDocument.document_date == SupplierProductCost.purchase_date,
        AADEDocument.issue_date == SupplierProductCost.purchase_date, AADEDocument.currency == "EUR",
        AADEDocument.issuer_vat == Supplier.vat_number, AADEDocument.document_direction == "expense",
        AADEDocument.invoice_type.in_(["1.1", "1.2", "1.3", "2.1", "2.2", "2.3"]),
        AADEDocument.is_cancelled.is_(False), AADEDocument.cancelled_by_mark.is_(None),
    ).subquery()
    results = db.execute(select(SupplierProductCost, Supplier.code, AADEDocument.mark)
        .join(eligible, eligible.c.cost_id == SupplierProductCost.id)
        .join(Supplier, Supplier.id == SupplierProductCost.supplier_id)
        .join(SupplierDocumentLine, SupplierDocumentLine.id == SupplierProductCost.source_line_id)
        .join(SupplierDocument, SupplierDocument.id == SupplierDocumentLine.document_id)
        .join(AADEDocument, AADEDocument.id == SupplierDocument.aade_document_id)
        .where(eligible.c.recency == 1).order_by(SupplierProductCost.id)).all()
    grouped = {}
    valid_ids = {cost.id for cost in validated_cost_rows(db, [cost for cost, _, _ in results])}
    for cost, code, mark in results:
        if cost.id not in valid_ids:
            continue
        grouped.setdefault((code, cost.product_catalog_id), []).append((cost, mark))
    return {key: (options[0] if len({cost.net_unit_cost for cost, _ in options}) == 1 else None)
            for key, options in grouped.items()}


def price_comparison(product, cost_option) -> dict:
    sale = catalog_sale_price(product)
    cost, mark = cost_option if cost_option else (None, None)
    metrics = margin_metrics(sale["inde_price_net"], 1, cost.net_unit_cost) if cost and sale["inde_price_net"] is not None else {}
    return {**sale, "aade_cost_net": cost.net_unit_cost if cost else None,
            "aade_cost_date": cost.purchase_date if cost else None, "aade_mark": mark,
            "gross_profit_per_unit": metrics.get("gross_profit"), "gross_margin_percent": metrics.get("margin_percent"),
            "margin_status": "missing_aade_cost" if not cost else "missing_sale_tax_basis" if sale["inde_price_net"] is None
            else "zero_sale_price" if sale["inde_price_net"] == 0 else "available"}
