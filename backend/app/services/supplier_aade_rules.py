"""Explicit AADE review identities, isolated from generic supplier imports."""

import hashlib

from sqlalchemy import select

from app.models import ProductCatalog, Supplier, SupplierProductMap
from app.services.supplier_costing import normalize_identifier


def review_identity(code, mark, line_number, digest, remember):
    value = normalize_identifier(code) if remember and code else f"{mark}:{line_number}:{digest}"
    prefix = "aade-code:" if remember and code else "aade-line:"
    return prefix + hashlib.sha256(value.encode()).hexdigest()


def product_identity(product):
    return {field: getattr(product, field) for field in ("sku", "model", "ean", "upc", "mpn")}


def xml_identity(item):
    return {field: item.get(field) if isinstance(item, dict) else getattr(item, field)
            for field in ("supplier_code", "supplier_sku", "ean")}


def reviewed_mapping(mappings, line, document, digest):
    identities = [review_identity(line["item_code"], document.mark, line["line_number"], digest, False)]
    if line["item_code"]:
        identities.append(review_identity(line["item_code"], document.mark, line["line_number"], digest, True))
    for identity in identities:
        mapping = next((row for row in mappings if row.identity_key == identity), None)
        if mapping:
            return mapping
    return None


def mapping_valid(mapping, product):
    review = (mapping.raw_metadata or {}).get("aade_review", {})
    return bool(product and mapping.verified and mapping.status == "matched"
                and mapping.match_method == "aade_manual_reviewed"
                and mapping.pack_quantity == mapping.conversion_factor == 1
                and review.get("product_identity") == product_identity(product))


def catalog_review_links(db, feed_code, catalog_rows):
    """Preserve human XML bridges only while both sides retain their identifiers."""
    mappings = db.scalars(select(SupplierProductMap).join(Supplier)
        .where(Supplier.code == feed_code, SupplierProductMap.match_method == "aade_manual_reviewed")).all()
    products = {row.id: row for row in catalog_rows}
    links = {}
    for mapping in mappings:
        review = (mapping.raw_metadata or {}).get("aade_review", {})
        if not review.get("remember") or not review.get("xml_identity"):
            continue
        code = review["xml_identity"]["supplier_code"]
        links.setdefault(code, []).append((mapping, mapping_valid(mapping, products.get(mapping.product_catalog_id))))
    return links
