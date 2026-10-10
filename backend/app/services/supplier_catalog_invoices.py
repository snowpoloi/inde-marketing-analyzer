"""Trace catalog purchase prices to verified AADE invoices."""

from app.models import AADEDocument, SupplierCatalogFeed, SupplierCatalogProduct, SupplierProductCost
from app.services.supplier_aade_costs import validated_cost_rows
from app.services.supplier_catalog_pricing import aade_cost_query, latest_aade_costs


def product_invoices(db, product_id, *, offset=0, limit=50):
    product = db.get(SupplierCatalogProduct, product_id)
    if product is None:
        raise LookupError("Supplier product not found.")
    result = {"rows": [], "total": 0, "offset": offset, "limit": limit}
    if not product.product_catalog_id or product.match_method == "ambiguous":
        return result
    feed = db.get(SupplierCatalogFeed, product.feed_id)
    rows = db.execute(aade_cost_query([feed.code])
        .where(SupplierProductCost.product_catalog_id == product.product_catalog_id)
        .add_columns(AADEDocument.id, AADEDocument.series, AADEDocument.aa)
        .order_by(SupplierProductCost.purchase_date.desc(), AADEDocument.mark, SupplierProductCost.id)).all()
    valid = {cost.id for cost in validated_cost_rows(db, [row[0] for row in rows])}
    latest = latest_aade_costs(db, [product.product_catalog_id], [feed.code]).get((feed.code, product.product_catalog_id))
    current_id = latest[0].id if latest else None
    grouped = {}
    for cost, _, mark, document_id, series, aa in rows:
        if cost.id not in valid:
            continue
        row = grouped.setdefault(document_id, {"document_id": str(document_id), "date": cost.purchase_date,
            "number": " / ".join(str(value) for value in (series, aa) if value) or mark,
            "mark": mark, "quantity": 0, "costs": set(), "current": False})
        row["quantity"] += cost.quantity
        row["costs"].add(cost.net_unit_cost)
        row["current"] |= cost.id == current_id
    invoices = [{**{key: value for key, value in row.items() if key != "costs"},
                 "unit_cost_min": min(row["costs"]), "unit_cost_max": max(row["costs"])}
                for row in grouped.values()]
    return {**result, "total": len(invoices), "rows": invoices[offset:offset + limit]}
