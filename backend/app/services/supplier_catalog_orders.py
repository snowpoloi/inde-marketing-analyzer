"""Read stored INDE orders for an explicitly matched supplier catalog product."""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import OpenCartOrder, OpenCartOrderProduct, ProductCatalog, SupplierCatalogProduct


def product_orders(db: Session, product_id, date_from: date, date_to: date, *, offset=0, limit=50):
    if date_from > date_to:
        raise ValueError("From date must be before or equal to To date.")
    supplier_product = db.get(SupplierCatalogProduct, product_id)
    if supplier_product is None:
        raise LookupError("Supplier product not found.")
    own = db.get(ProductCatalog, supplier_product.product_catalog_id) if supplier_product.product_catalog_id else None
    result = {"rows": [], "total": 0, "offset": offset, "limit": limit,
              "date_from": date_from, "date_to": date_to, "match_status": "unmatched"}
    if own is None or supplier_product.match_method == "ambiguous":
        return result

    line = OpenCartOrderProduct
    missing_id = or_(line.product_id.is_(None), func.trim(line.product_id) == "")
    missing_sku = or_(line.sku.is_(None), func.trim(line.sku) == "")
    predicates = []
    # Do not confuse supplier codes with INDE identifiers, or use name matching.
    unique_id = bool(own.product_id and db.scalar(select(func.count()).select_from(ProductCatalog)
                                                .where(ProductCatalog.product_id == own.product_id)) == 1)
    if unique_id:
        predicates.append(line.product_id == own.product_id)
    fallback = []
    if own.sku:
        fallback.append(line.sku == own.sku)
    if own.model and db.scalar(select(func.count()).select_from(ProductCatalog)
                              .where(ProductCatalog.model == own.model)) == 1:
        fallback.append(and_(missing_sku, line.model == own.model))
    if fallback:
        # An explicit, different product ID always wins over a reused SKU/model.
        allowed_id = missing_id if own.product_id else ~select(ProductCatalog.id).where(
            ProductCatalog.product_id == line.product_id, ProductCatalog.id != own.id).exists()
        predicates.append(and_(allowed_id, or_(*fallback)))
    if not predicates:
        result["match_status"] = "ambiguous"
        return result

    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
    conditions = [or_(*predicates),
                  OpenCartOrder.date_added >= start, OpenCartOrder.date_added < end]
    grouped = (select(OpenCartOrder.id.label("id"), func.sum(line.quantity).label("quantity"))
               .join(line, line.order_pk == OpenCartOrder.id).where(*conditions)
               .group_by(OpenCartOrder.id).subquery())
    result["match_status"] = "matched"
    result["total"] = db.scalar(select(func.count()).select_from(grouped)) or 0
    orders = db.execute(select(OpenCartOrder.order_id, OpenCartOrder.date_added,
                               OpenCartOrder.order_status, grouped.c.quantity)
                        .join(grouped, grouped.c.id == OpenCartOrder.id)
                        .order_by(OpenCartOrder.date_added.desc(), OpenCartOrder.order_id.desc())
                        .offset(offset).limit(limit)).all()
    result["rows"] = [{"order_id": row.order_id, "date_added": row.date_added,
                       "order_status": row.order_status, "quantity": int(row.quantity or 0)} for row in orders]
    return result
