from __future__ import annotations

import base64
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, load_only

from app.connectors.supplier_catalog import fetch_megapap_catalog, fetch_pakoworld_catalog, validate_feed_url
from app.core.config import settings
from app.models import ProductCatalog, SupplierCatalogFeed, SupplierCatalogProduct
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services.supplier_costing import normalize_identifier
from app.services.supplier_catalog_pricing import (catalog_prices, latest_aade_costs, price_comparison,
    sale_quantity, sale_step_field, xml_sale_prices)
from app.services.supplier_catalog_settings import pricing_settings


def _cipher() -> Fernet:
    if not settings.secret_key or settings.secret_key == "change-me":
        raise ValueError("A private application SECRET_KEY is required for supplier feeds.")
    key = hashlib.sha256(("supplier-catalog:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def feed_response(feed: SupplierCatalogFeed) -> dict:
    return {"id": str(feed.id), "code": feed.code, "name": feed.name, "adapter": feed.adapter,
            "configured": bool(feed.encrypted_url), "is_enabled": feed.is_enabled,
            "refresh_hours": feed.refresh_hours, "status": feed.status, "error": feed.error,
            "last_synced_at": feed.last_synced_at, "counts": feed.counts or {}}


def save_feed(db: Session, payload: SupplierCatalogFeedInput, feed_id: UUID | None = None) -> SupplierCatalogFeed:
    feed = db.scalar(select(SupplierCatalogFeed).where(SupplierCatalogFeed.id == feed_id).with_for_update()) if feed_id else None
    if feed_id and feed is None:
        raise LookupError("Supplier feed not found.")
    if feed and feed.status == "running":
        raise ValueError("Wait for the supplier sync to finish before editing its settings.")
    if feed and feed.adapter != payload.adapter and not payload.url:
        validate_feed_url(_cipher().decrypt(feed.encrypted_url.encode()).decode(), payload.adapter)
    code = payload.code.upper()
    existing = db.scalar(select(SupplierCatalogFeed.id).where(SupplierCatalogFeed.code == code))
    if existing and existing != feed_id:
        raise ValueError("A supplier feed with this code already exists.")
    if feed is None:
        if not payload.url:
            raise ValueError("An XML URL is required for a new supplier feed.")
        feed = SupplierCatalogFeed(code=code, name=payload.name, adapter=payload.adapter,
                                   encrypted_url=_cipher().encrypt(payload.url.encode()).decode())
        db.add(feed)
    changed = bool(payload.url) or feed.adapter != payload.adapter
    if payload.url:
        feed.encrypted_url = _cipher().encrypt(payload.url.encode()).decode()
    feed.code, feed.name, feed.adapter = code, payload.name, payload.adapter
    feed.is_enabled, feed.refresh_hours = payload.is_enabled, payload.refresh_hours
    if changed:
        feed.status, feed.error, feed.requested_at = "idle", None, None
        feed.next_sync_at = datetime.now(timezone.utc)
    elif feed.last_synced_at:
        feed.next_sync_at = feed.last_synced_at + timedelta(hours=payload.refresh_hours)
    db.commit()
    db.refresh(feed)
    return feed


def queue_feed(db: Session, feed_id: UUID) -> SupplierCatalogFeed:
    feed = db.scalar(select(SupplierCatalogFeed).where(SupplierCatalogFeed.id == feed_id).with_for_update())
    if feed is None:
        raise LookupError("Supplier feed not found.")
    if feed.status != "running":
        feed.requested_at, feed.status, feed.error = datetime.now(timezone.utc), "queued", None
    db.commit()
    return feed


def build_catalog_index(catalogs) -> dict[str, dict[str, set]]:
    index = {key: defaultdict(set) for key in ("sku", "model", "ean", "mpn")}
    for catalog in catalogs:
        for field in index:
            value = normalize_identifier(getattr(catalog, field))
            if value:
                index[field][value].add(catalog.id)
        if catalog.upc:
            index["ean"][normalize_identifier(catalog.upc)].add(catalog.id)
    return index


def match_supplier_product(row: dict, index: dict, adapter: str = "megapap") -> tuple[UUID | None, str]:
    candidates = set()
    sku, ean, code = (normalize_identifier(row.get(field)) for field in ("supplier_sku", "ean", "supplier_code"))
    if sku:
        candidates |= index["sku"].get(sku, set()) | index["model"].get(sku, set())
    if ean:
        candidates |= index["ean"].get(ean, set())
    if code:
        candidates |= index["mpn"].get(code, set()) | index["model"].get(code, set())
        if adapter == "pakoworld":
            candidates |= index["sku"].get(code, set())
    if len(candidates) == 1:
        return next(iter(candidates)), "exact_identifiers"
    return None, "ambiguous" if candidates else "unmatched"


def apply_catalog(db: Session, feed: SupplierCatalogFeed, rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("An empty supplier catalog cannot replace the current catalog.")
    catalog_rows = db.execute(select(ProductCatalog.id, ProductCatalog.sku, ProductCatalog.model,
                                   ProductCatalog.ean, ProductCatalog.upc, ProductCatalog.mpn)).all()
    index = build_catalog_index(catalog_rows)
    now = datetime.now(timezone.utc)
    matched = ambiguous = 0
    values = []
    for row in rows:
        product_id, method = match_supplier_product(row, index, feed.adapter)
        matched += product_id is not None
        ambiguous += method == "ambiguous"
        values.append({**row, "id": uuid4(), "feed_id": feed.id, "product_catalog_id": product_id,
                       "match_method": method, "is_current": True, "last_seen_at": now})
    db.execute(update(SupplierCatalogProduct).where(SupplierCatalogProduct.feed_id == feed.id).values(is_current=False))
    for offset in range(0, len(values), 250):
        statement = insert(SupplierCatalogProduct).values(values[offset:offset + 250])
        fields = set(values[0]) - {"id", "feed_id", "supplier_code"}
        db.execute(statement.on_conflict_do_update(
            constraint="uq_supplier_catalog_product_identity",
            set_={**{field: getattr(statement.excluded, field) for field in fields}, "updated_at": now},
        ))
    return {"products": len(rows), "matched": matched, "ambiguous": ambiguous, "unmatched": len(rows) - matched - ambiguous}


def process_supplier_catalog(db: Session) -> dict | None:
    now = datetime.now(timezone.utc)
    # Claim one feed with a bounded lease. Network work never runs in an HTTP request.
    feed = db.scalar(select(SupplierCatalogFeed).where(
        or_(SupplierCatalogFeed.status != "running", SupplierCatalogFeed.started_at < now - timedelta(minutes=30)),
        or_(SupplierCatalogFeed.requested_at.is_not(None),
            (SupplierCatalogFeed.is_enabled.is_(True) & or_(SupplierCatalogFeed.next_sync_at.is_(None), SupplierCatalogFeed.next_sync_at <= now))),
    ).order_by(SupplierCatalogFeed.requested_at.asc().nullslast(), SupplierCatalogFeed.created_at)
        .with_for_update(skip_locked=True).limit(1))
    if feed is None:
        return None
    feed.status, feed.started_at = "running", now
    feed.next_sync_at = now + timedelta(minutes=30)
    db.commit()
    feed_id = feed.id
    try:
        fetch_catalog = {"megapap": fetch_megapap_catalog, "pakoworld": fetch_pakoworld_catalog}.get(feed.adapter)
        if fetch_catalog is None:
            raise ValueError("Supplier XML format is not yet supported.")
        rows = fetch_catalog(_cipher().decrypt(feed.encrypted_url.encode()).decode())
        counts = apply_catalog(db, feed, rows)
        feed.status, feed.error, feed.counts = "success", None, counts
        feed.last_synced_at = datetime.now(timezone.utc)
        feed.next_sync_at = feed.last_synced_at + timedelta(hours=feed.refresh_hours)
        feed.requested_at = None
        db.commit()
        return counts
    except Exception as exc:
        db.rollback()
        feed = db.get(SupplierCatalogFeed, feed_id)
        feed.status, feed.requested_at = "failed", None
        # Exceptions from HTTP/XML libraries can contain credential-bearing URLs/content.
        feed.error = "Supplier XML sync failed. Previous catalog retained."
        if isinstance(exc, ValueError) and str(exc).startswith(("Supplier XML ", "Duplicate supplier ", "A supplier product ", "This XML ", "Too many supplier ")):
            feed.error = str(exc)
        feed.next_sync_at = datetime.now(timezone.utc) + timedelta(hours=6)
        db.commit()
        return {"failed": True}


def catalog_products(db: Session, *, feed_id: UUID | None, q: str, match: str, availability: str,
                     category: str, offset: int, limit: int, has_margin: bool = False,
                     sort_by: str = "name", sort_direction: str = "asc") -> dict:
    conditions = [SupplierCatalogProduct.is_current.is_(True)]
    if feed_id:
        conditions.append(SupplierCatalogProduct.feed_id == feed_id)
    if q:
        literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(or_(*(field.ilike(f"%{literal}%", escape="\\") for field in
            (SupplierCatalogProduct.name, SupplierCatalogProduct.supplier_code, SupplierCatalogProduct.supplier_sku, SupplierCatalogProduct.ean, ProductCatalog.sku))))
    if match == "matched":
        conditions.append(ProductCatalog.id.is_not(None))
    elif match == "unmatched":
        conditions.append(ProductCatalog.id.is_(None))
    if availability == "in_stock":
        conditions.append(SupplierCatalogProduct.quantity > 0)
    elif availability == "out_of_stock":
        conditions.append(SupplierCatalogProduct.quantity == 0)
    if category:
        conditions.append(SupplierCatalogProduct.category == category)
    base = select(SupplierCatalogProduct, SupplierCatalogFeed.name, SupplierCatalogFeed.code, ProductCatalog).join(
        SupplierCatalogFeed, SupplierCatalogFeed.id == SupplierCatalogProduct.feed_id).outerjoin(
        ProductCatalog, ProductCatalog.id == SupplierCatalogProduct.product_catalog_id).where(*conditions)
    pricing = pricing_settings(db)
    financial_fields = {"inde_price", "aade_cost_net", "aade_cost_sale_net", "gross_profit_per_unit", "gross_profit_per_sale", "gross_margin_percent",
                        "sale_quantity", "wholesale_price_net", "retail_price_gross"}
    sort_fields = {"name": SupplierCatalogProduct.name, "supplier_code": SupplierCatalogProduct.supplier_code,
                   "supplier_sku": func.coalesce(SupplierCatalogProduct.supplier_sku, SupplierCatalogProduct.ean),
                   "opencart_sku": ProductCatalog.sku, "quantity": SupplierCatalogProduct.quantity,
                   "wholesale_price_net": SupplierCatalogProduct.wholesale_price_net,
                   "retail_price_gross": SupplierCatalogProduct.retail_price_gross}
    if sort_by not in financial_fields | sort_fields.keys() or sort_direction not in {"asc", "desc"}:
        raise ValueError("Invalid catalog sort.")
    costs = None
    ordered_ids = None
    if has_margin or sort_by in financial_fields:
        candidates = db.execute(base.with_only_columns(SupplierCatalogProduct.id, SupplierCatalogFeed.code,
            ProductCatalog.id.label("own_id"), sort_fields.get(sort_by, SupplierCatalogProduct.name).label("sort_value"),
            SupplierCatalogFeed.adapter, sale_step_field().label("step"),
            SupplierCatalogProduct.wholesale_price_net, SupplierCatalogProduct.retail_price_gross,
            maintain_column_froms=True).order_by(SupplierCatalogFeed.name, SupplierCatalogProduct.name, SupplierCatalogProduct.id)).all()
        costs = latest_aade_costs(db, {row.own_id for row in candidates if row.own_id}, {row.code for row in candidates})
        price_ids = {row.own_id for row in candidates if row.own_id and (sort_by == "inde_price" or costs.get((row.code, row.own_id)))}
        prices = catalog_prices(db, price_ids)
        comparisons = {row.id: {**xml_sale_prices(sale_quantity(row.adapter, row.step), row.wholesale_price_net, row.retail_price_gross),
            **price_comparison(prices.get(row.own_id), costs.get((row.code, row.own_id)),
                confirmed_vat_rate=pricing.get("sale_vat_rate"), sale_quantity=sale_quantity(row.adapter, row.step))} for row in candidates}
        candidates = [row for row in candidates if not has_margin or comparisons[row.id]["gross_margin_percent"] is not None]
        value = lambda row: comparisons[row.id][sort_by] if sort_by in financial_fields else row.sort_value
        present = [row for row in candidates if value(row) is not None]
        missing = [row for row in candidates if value(row) is None]
        present.sort(key=value, reverse=sort_direction == "desc")
        total = len(candidates)
        ordered_ids = [row.id for row in (present + missing)[offset:offset + limit]]
        page = base.where(SupplierCatalogProduct.id.in_(ordered_ids))
    else:
        field = sort_fields[sort_by]
        order = field.desc() if sort_direction == "desc" else field.asc()
        total = db.scalar(select(func.count()).select_from(base.with_only_columns(SupplierCatalogProduct.id).subquery()))
        page = base.order_by(order.nullslast(), SupplierCatalogFeed.name, SupplierCatalogProduct.id).offset(offset).limit(limit)
    results = db.execute(page.options(load_only(ProductCatalog.id, ProductCatalog.sku, ProductCatalog.price, ProductCatalog.raw),
        load_only(SupplierCatalogProduct.id, SupplierCatalogProduct.supplier_code, SupplierCatalogProduct.supplier_sku,
                  SupplierCatalogProduct.ean, SupplierCatalogProduct.name, SupplierCatalogProduct.category,
                  SupplierCatalogProduct.image_url, SupplierCatalogProduct.quantity, SupplierCatalogProduct.wholesale_price_net,
                  SupplierCatalogProduct.retail_price_gross, SupplierCatalogProduct.match_method, SupplierCatalogProduct.last_seen_at))).all()
    if ordered_ids is not None:
        positions = {value: index for index, value in enumerate(ordered_ids)}
        results.sort(key=lambda row: positions[row[0].id])
    if costs is None:
        costs = latest_aade_costs(db, {own.id for _, _, _, own in results if own}, {code for _, _, code, _ in results})
    steps = {row.id: sale_quantity(row.adapter, row.step) for row in db.execute(select(SupplierCatalogProduct.id,
        SupplierCatalogFeed.adapter, sale_step_field().label("step")).join(SupplierCatalogFeed,
        SupplierCatalogFeed.id == SupplierCatalogProduct.feed_id).where(SupplierCatalogProduct.id.in_([row[0].id for row in results])))}
    summary = db.execute(select(func.count(), func.sum(case((ProductCatalog.id.is_not(None), 1), else_=0)))
                         .select_from(SupplierCatalogProduct).outerjoin(ProductCatalog, ProductCatalog.id == SupplierCatalogProduct.product_catalog_id)
                         .where(SupplierCatalogProduct.is_current.is_(True), *([SupplierCatalogProduct.feed_id == feed_id] if feed_id else []))).one()
    categories = db.scalars(select(SupplierCatalogProduct.category).where(
        SupplierCatalogProduct.is_current.is_(True), SupplierCatalogProduct.category.is_not(None),
        *([SupplierCatalogProduct.feed_id == feed_id] if feed_id else []))
        .distinct().order_by(SupplierCatalogProduct.category).limit(500)).all()
    rows = [{"id": str(product.id), "supplier": supplier, "supplier_code": product.supplier_code,
             "supplier_sku": product.supplier_sku, "ean": product.ean, "name": product.name,
             "category": product.category, "image_url": product.image_url, "quantity": product.quantity,
             **xml_sale_prices(steps[product.id], product.wholesale_price_net, product.retail_price_gross),
             "opencart_sku": own.sku if own else None, "match_method": product.match_method if own else ("ambiguous" if product.match_method == "ambiguous" else "unmatched"),
             **price_comparison(own, costs.get((code, own.id)) if own else None, confirmed_vat_rate=pricing.get("sale_vat_rate"), sale_quantity=steps[product.id]),
             "last_seen_at": product.last_seen_at} for product, supplier, code, own in results]
    return {"rows": rows, "total": total, "offset": offset, "limit": limit, "categories": categories,
            "summary": {"products": summary[0], "matched": summary[1] or 0, "unmatched": summary[0] - (summary[1] or 0)}}
