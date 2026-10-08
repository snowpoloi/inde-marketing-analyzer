"""Period purchases and quantity-weighted catalog margins, not realized sales."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.models import AADEDocument, Supplier, SupplierCatalogFeed, SupplierProductCost
from app.services.supplier_aade_costs import own_vat, validated_cost_rows
from app.services.supplier_catalog_pricing import aade_cost_query, catalog_prices, catalog_sale_price
from app.services.supplier_catalog_settings import pricing_settings
from app.services.supplier_costing import money
from app.services.supplier_identity import normalize_vat


def period_summary(db, start, end, feed_id=None):
    recipient = own_vat(db)
    if not recipient:
        raise ValueError("Configure the INDE AFM in AADE settings first.")
    feeds = db.execute(select(SupplierCatalogFeed, Supplier).outerjoin(Supplier,
        Supplier.code == SupplierCatalogFeed.code).where(
        *([SupplierCatalogFeed.id == feed_id] if feed_id else [])).order_by(SupplierCatalogFeed.name)).all()
    codes = {feed.code for feed, supplier in feeds if supplier}
    vats = {normalize_vat(supplier.vat_number) for _, supplier in feeds if supplier and supplier.vat_number}
    fiscal = db.execute(select(AADEDocument.id, AADEDocument.mark, AADEDocument.uid, AADEDocument.issuer_vat,
        AADEDocument.invoice_type, AADEDocument.net_value, AADEDocument.is_cancelled, AADEDocument.cancelled_by_mark,
        func.coalesce(AADEDocument.raw["record_type"].astext, "full_document").label("record_type"))
        .where(AADEDocument.issue_date.between(start, min(end, date.today())),
            AADEDocument.document_direction == "expense", AADEDocument.currency == "EUR",
            AADEDocument.counterpart_vat.in_([recipient, "EL" + recipient]),
            AADEDocument.issuer_vat.in_(vats | {"EL" + vat for vat in vats}),
            AADEDocument.invoice_type.in_(["1.1", "1.2", "1.3", "5.1", "5.2"]))).all()
    groups = defaultdict(list)
    for row in fiscal:
        if row.record_type == "full_document":
            groups[(normalize_vat(row.issuer_vat), row.mark or row.uid or str(row.id))].append(row)
    marks = {row.mark for row in fiscal if row.mark}
    cancelled = set(db.scalars(select(AADEDocument.mark).where(AADEDocument.mark.in_(marks),
        or_(AADEDocument.is_cancelled.is_(True), AADEDocument.cancelled_by_mark.is_not(None))))) if marks else set()
    totals = defaultdict(lambda: {"purchases_net": Decimal(0), "credits_net": Decimal(0), "invoices": 0,
                                  "credit_notes": 0, "excluded_conflicts": 0})
    valid_marks = set()
    for (vat, identity), copies in groups.items():
        if any(row.is_cancelled or row.cancelled_by_mark or row.mark in cancelled for row in copies):
            continue
        if len({(row.invoice_type, abs(row.net_value) if row.invoice_type in {"5.1", "5.2"} else row.net_value) for row in copies}) != 1:
            totals[vat]["excluded_conflicts"] += 1
            continue
        row = copies[0]
        credit = row.invoice_type in {"5.1", "5.2"}
        totals[vat]["credits_net" if credit else "purchases_net"] += abs(row.net_value)
        totals[vat]["credit_notes" if credit else "invoices"] += 1
        if not credit and row.mark:
            valid_marks.add(row.mark)
    results = db.execute(aade_cost_query(codes).where(SupplierProductCost.purchase_date.between(start, end))).all() if codes else []
    valid_costs = {cost.id for cost in validated_cost_rows(db, [cost for cost, _, _ in results])}
    by_line = defaultdict(list)
    for cost, code, mark in results:
        if cost.id in valid_costs and mark in valid_marks:
            by_line[(code, cost.source_line_id)].append(cost)
    costs = []
    for (code, _), copies in by_line.items():
        if len({(row.product_catalog_id, row.net_unit_cost, row.quantity, row.net_line_total) for row in copies}) == 1:
            costs.append((code, copies[0]))
    prices = catalog_prices(db, {cost.product_catalog_id for _, cost in costs})
    rate = pricing_settings(db).get("sale_vat_rate")
    estimates = defaultdict(lambda: {"costed_units": Decimal(0), "priced_units": Decimal(0),
        "costed_products_net": Decimal(0), "priced_cost_net": Decimal(0), "catalog_sales_net": Decimal(0)})
    for code, cost in costs:
        value = estimates[code]
        value["costed_units"] += cost.quantity
        value["costed_products_net"] += cost.net_line_total
        sale = catalog_sale_price(prices.get(cost.product_catalog_id), confirmed_vat_rate=rate)["inde_price_net"]
        if sale is not None and sale > 0:
            value["priced_units"] += cost.quantity
            value["priced_cost_net"] += cost.net_line_total
            value["catalog_sales_net"] += sale * cost.quantity
    rows = []
    for feed, supplier in feeds:
        actual = totals[normalize_vat(supplier.vat_number)] if supplier else totals[""]
        estimate = estimates[feed.code]
        sales = estimate["catalog_sales_net"]
        profit = sales - estimate["priced_cost_net"]
        rows.append({"feed_id": str(feed.id), "supplier": feed.name,
            "supplier_id": str(supplier.id) if supplier else None, "vat_number": supplier.vat_number if supplier else None,
            **actual, "net_purchases": money(actual["purchases_net"] - actual["credits_net"]), **estimate,
            "average_profit_per_unit": money(profit / estimate["priced_units"]) if estimate["priced_units"] else None,
            "average_margin_percent": money(profit / sales * 100) if sales else None,
            "catalog_profit_net": money(profit) if estimate["priced_units"] else None})
    return {"rows": rows, "date_from": start, "date_to": end,
            "margin_basis": "current_catalog_prices_weighted_by_period_purchase_quantities"}
