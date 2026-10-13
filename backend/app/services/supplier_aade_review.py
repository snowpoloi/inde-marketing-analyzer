"""Line-level human confirmations. Financial values always come from AADE."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib

from sqlalchemy import String, case, func, or_, select, text

from app.models import (AADEDocument, ProductCatalog, Supplier, SupplierCatalogFeed, SupplierCatalogProduct,
                        SupplierDocument, SupplierProductCost, SupplierProductMap)
from app.schemas.suppliers import SupplierAADEAcceptRequest
from app.services.supplier_aade_costs import invoice_preview, accept_invoice, _invoice_key
from app.services.supplier_aade_rules import review_identity, product_identity, xml_identity
from app.services.supplier_catalog_settings import pricing_settings, queue_cost_refresh
from app.services.supplier_costing import money
from app.connectors.aade_detail import META_KEY, detail_info, source_fingerprint


def pending_costs(db, start, end, supplier_id=None, offset=0, limit=10):
    # Page fiscal documents, not the XML catalog. Deduplicate endpoints by MARK
    # before loading detail, preferring full invoices over bookkeeping summaries.
    vat = func.regexp_replace(func.upper(func.trim(AADEDocument.issuer_vat)), r"^EL", "")
    supplier_vat = func.regexp_replace(func.upper(func.trim(Supplier.vat_number)), r"^EL", "")
    full = func.coalesce(AADEDocument.raw["record_type"].astext, "full_document") == "full_document"
    ranked = select(AADEDocument.id.label("document_id"), Supplier.id.label("supplier_id"),
        AADEDocument.issue_date.label("date"), func.row_number().over(
            partition_by=(Supplier.id, func.coalesce(AADEDocument.mark, AADEDocument.id.cast(String))),
            order_by=(case((full, 0), else_=1), AADEDocument.id)).label("rank"))\
        .join(Supplier, supplier_vat == vat).outerjoin(SupplierDocument,
            SupplierDocument.identity_key == func.concat("aade:", supplier_vat, ":", AADEDocument.mark))\
        .where(AADEDocument.document_direction == "expense", AADEDocument.invoice_type.in_(["1.1", "1.2", "1.3"]),
            AADEDocument.issue_date.between(start, end),
            or_(SupplierDocument.id.is_(None), SupplierDocument.raw_metadata["aade_partial"].astext == "true"),
            *([Supplier.id == supplier_id] if supplier_id else [])).subquery()
    query = select(ranked.c.document_id, ranked.c.supplier_id).where(ranked.c.rank == 1)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(ranked.c.date.desc(), ranked.c.document_id, ranked.c.supplier_id)
                      .offset(offset).limit(limit)).all()
    policy = pricing_settings(db)
    piece_suppliers = set(policy.get("piece_supplier_ids", []))
    invoices, cache = [], {}
    for document_id, identity in rows:
        source = db.get(AADEDocument, document_id)
        stored = db.scalar(select(SupplierDocument).where(SupplierDocument.identity_key == _invoice_key(source)))
        units = str(identity) in piece_suppliers or bool(stored and (stored.raw_metadata or {}).get("aade_confirm_missing_units"))
        preview = invoice_preview(db, document_id, identity, confirm_missing_units=units, matching_cache=cache)
        pending = [line for line in preview["lines"] if line["line_type"] == "product" and not line["costed"]]
        for line in pending:
            line["invoice_unit_cost_net"] = money(line["net_value"] / line["quantity"]) if (
                line["net_value"] is not None and line["net_value"] >= 0 and line["quantity"] and line["quantity"] > 0) else None
        invoices.append({**preview, "lines": pending})
    return {"invoices": invoices, "total": total, "offset": offset, "limit": limit}


def confirm_line(db, document_id, payload, user):
    if not payload.confirm_products_and_units:
        raise ValueError("Confirm the selected product and one purchased unit equals one physical product piece.")
    db.execute(text("SELECT pg_advisory_xact_lock(841650721)"))
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise ValueError("Supplier not found.")
    lock_key = int.from_bytes(hashlib.sha256(supplier.code.encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    feeds = db.scalars(select(SupplierCatalogFeed).where(SupplierCatalogFeed.code == supplier.code).with_for_update()).all()
    if any(feed.status == "running" for feed in feeds):
        raise ValueError("Supplier XML is updating. Wait for it to finish, then reload this invoice.")
    before = invoice_preview(db, document_id, supplier.id, lock=True,
                             confirm_missing_units=payload.preview_confirm_missing_units)
    if before["source_digest"] != payload.source_digest or before["reasons"]:
        raise ValueError("Fiscal source changed or needs review. Reload this invoice; no costs saved.")
    line = next((row for row in before["lines"] if row["line_number"] == payload.line_number), None)
    if not line or line["line_type"] != "product":
        raise ValueError("Product invoice line not found.")
    if line["costed"]:
        if line["product_catalog_id"] == str(payload.product_catalog_id) and not line["reasons"]:
            return {"duplicate": True, "costs_created": 0, "pending_lines": before["pending_lines"]}
        raise ValueError("This line already has cost evidence. Existing costs cannot be reassigned here.")
    if before["fingerprint"] != payload.fingerprint:
        raise ValueError("Invoice / mapping changed. Reload and review the current values before confirming.")
    if payload.preview_confirm_missing_units and not payload.confirm_missing_units:
        raise ValueError("Keep the existing physical-piece confirmation for this invoice.")
    if payload.remember_match and not line["item_code"]:
        raise ValueError("A missing invoice code can only be confirmed for this invoice line, not future invoices.")
    product = db.get(ProductCatalog, payload.product_catalog_id, with_for_update=True)
    if product is None:
        raise ValueError("Selected INDE product no longer exists.")
    identity = review_identity(line["item_code"], before["mark"], payload.line_number, payload.source_digest, payload.remember_match)
    mapping = db.scalar(select(SupplierProductMap).where(SupplierProductMap.supplier_id == supplier.id,
        SupplierProductMap.identity_key == identity).with_for_update())
    if mapping and mapping.product_catalog_id != product.id and db.scalar(select(SupplierProductCost.id)
            .where(SupplierProductCost.supplier_product_map_id == mapping.id).limit(1)):
        raise ValueError("This saved code is already used by another product. Uncheck future-invoice matching to confirm only this line.")
    if mapping is None:
        mapping = SupplierProductMap(supplier_id=supplier.id, identity_key=identity)
        db.add(mapping)
    # A unique XML identity can be bridged too. Ambiguous XML rows are never
    # linked en masse just because their invoice code happens to be the same.
    item = db.get(SupplierCatalogProduct, line["xml_candidates"][0]["id"], with_for_update=True) if len(line["xml_candidates"]) == 1 else None
    mapping.product_catalog_id = product.id
    mapping.supplier_code = item.supplier_code if item else (line["item_code"] or None)
    mapping.supplier_sku, mapping.supplier_ean = (item.supplier_sku, item.ean) if item else (None, None)
    mapping.opencart_product_id, mapping.opencart_sku, mapping.opencart_model = product.product_id, product.sku, product.model
    mapping.product_name = product.name
    mapping.pack_quantity = mapping.conversion_factor = Decimal("1")
    mapping.purchase_unit, mapping.sales_unit = "piece", "piece"
    mapping.status, mapping.confidence, mapping.verified = "matched", Decimal("1"), True
    mapping.match_method, mapping.verified_by, mapping.verified_at = "aade_manual_reviewed", user.id, datetime.now(timezone.utc)
    audit = list((mapping.raw_metadata or {}).get("verification_audit", []))
    audit.append({"user_id": str(user.id), "at": mapping.verified_at.isoformat(), "method": mapping.match_method,
        "aade_mark": before["mark"], "line_number": payload.line_number, "product": str(product.id), "factor": "1"})
    mapping.raw_metadata = {**(mapping.raw_metadata or {}), "verification_audit": audit, "aade_review": {
        "remember": payload.remember_match, "invoice_code": line["item_code"], "mark": before["mark"],
        "line_number": payload.line_number, "source_digest": payload.source_digest,
        "missing_unit_is_piece": payload.confirm_missing_units,
        "product_identity": product_identity(product), "catalog_item_id": str(item.id) if item else None,
        "xml_identity": xml_identity(item) if item else None}}
    db.flush()
    after = invoice_preview(db, document_id, supplier.id, lock=True, confirm_missing_units=payload.preview_confirm_missing_units)
    selected = next(row for row in after["lines"] if row["line_number"] == payload.line_number)
    if after["reasons"] or not selected["ready"]:
        raise ValueError("This line still needs review: " + "; ".join(after["reasons"] + selected["reasons"]))
    if item and payload.remember_match:
        item.product_catalog_id, item.match_method = product.id, "manual_aade"
        db.flush()
        after = invoice_preview(db, document_id, supplier.id, lock=True, confirm_missing_units=payload.preview_confirm_missing_units)
    # Wake historical partial invoices in the same transaction as the approval.
    queue_cost_refresh(db)
    source = db.get(AADEDocument, document_id)
    raw = source.raw or {}
    if detail_info(raw)["status"] == "verified":
        raw = {**raw, META_KEY: {**raw[META_KEY], "source_hash": source_fingerprint(raw)}}
    pending = [row for row in after["lines"] if row["line_type"] == "product" and not row["costed"]
               and row["line_number"] != payload.line_number]
    source.raw = {**raw, "_catalog_cost": {**raw.get("_catalog_cost", {}),
        "status": "partial" if pending else "imported", "pending_lines": len(pending),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reasons": list(dict.fromkeys(reason for row in pending for reason in row["reasons"]))}}
    db.flush()
    return accept_invoice(db, document_id, SupplierAADEAcceptRequest(supplier_id=supplier.id,
        fingerprint=after["fingerprint"], confirm_products_and_units=True,
        confirm_missing_units=payload.preview_confirm_missing_units), user, only_line_number=payload.line_number)
