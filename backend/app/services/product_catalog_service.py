from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OpenCartOrderProduct, ProductCatalog


def _lookup_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _catalog_lookup(db: Session) -> dict[str, ProductCatalog]:
    lookup: dict[str, ProductCatalog] = {}
    for product in db.scalars(select(ProductCatalog)).all():
        raw = product.raw or {}
        for value in (
            product.sku,
            product.model,
            product.product_id,
            raw.get("mpn"),
            raw.get("isbn"),
            raw.get("upc"),
            raw.get("ean"),
            raw.get("jan"),
        ):
            key = _lookup_key(value)
            if key:
                lookup[key] = product
    return lookup


def _catalog_for_order_product(order_product: OpenCartOrderProduct, lookup: dict[str, ProductCatalog]) -> ProductCatalog | None:
    raw = order_product.raw or {}
    for value in (
        order_product.sku,
        order_product.model,
        order_product.product_id,
        raw.get("mpn"),
        raw.get("isbn"),
        raw.get("upc"),
        raw.get("ean"),
        raw.get("jan"),
    ):
        catalog = lookup.get(_lookup_key(value))
        if catalog:
            return catalog
    return None


def _catalog_snapshot(catalog: ProductCatalog) -> dict[str, Any]:
    return {
        "sku": catalog.sku,
        "model": catalog.model,
        "product_id": catalog.product_id,
        "brand": catalog.brand,
        "manufacturer": catalog.manufacturer,
        "category": catalog.category,
        "category_path": catalog.category_path,
        "status": catalog.status,
        "quantity": catalog.quantity,
        "price": str(catalog.price),
        "link": catalog.link,
        "image_url": catalog.image_url,
    }


def enrich_order_products_from_catalog(db: Session) -> int:
    lookup = _catalog_lookup(db)
    if not lookup:
        return 0

    updated = 0
    for order_product in db.scalars(select(OpenCartOrderProduct)).all():
        catalog = _catalog_for_order_product(order_product, lookup)
        if not catalog:
            continue

        changed = False
        for field_name, value in (
            ("sku", catalog.sku),
            ("model", catalog.model),
            ("product_id", catalog.product_id),
        ):
            if value and not getattr(order_product, field_name):
                setattr(order_product, field_name, value)
                changed = True

        for field_name, value in (
            ("manufacturer", catalog.manufacturer or catalog.brand),
            ("brand", catalog.brand or catalog.manufacturer),
            ("category", catalog.category),
        ):
            if value and getattr(order_product, field_name) != value:
                setattr(order_product, field_name, value)
                changed = True

        if order_product.name == "Unknown product" and catalog.name:
            order_product.name = catalog.name
            changed = True

        raw = dict(order_product.raw or {})
        next_raw = {**raw, "catalog": _catalog_snapshot(catalog)}
        if next_raw != raw:
            order_product.raw = next_raw
            changed = True

        if changed:
            updated += 1

    if updated:
        db.commit()
    return updated
