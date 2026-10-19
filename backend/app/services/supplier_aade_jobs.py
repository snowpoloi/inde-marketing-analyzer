"""Bounded background costing, with line-level retries after source syncs."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import String, and_, case, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.connectors.aade_detail import META_KEY, detail_info, source_fingerprint
from app.models import AADEDocument, Supplier, SupplierCatalogFeed, SupplierDocument, User
from app.schemas.suppliers import SupplierAADEAcceptRequest
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, upgrade_source_digest
from app.services.supplier_catalog_settings import pricing_settings
from app.services.supplier_aade_rules import DIRECT_SKU_SUPPLIERS


def process_aade_costs(db):
    policy = pricing_settings(db)
    if not policy.get("automatic_costs") or not policy.get("authorized_by"):
        return {"processed": 0}
    actor = db.get(User, UUID(policy["authorized_by"]))
    if not actor or not actor.is_active or not actor.is_admin:
        return {"processed": 0}
    # Skip overlapping workers. The import routine independently locks and
    # deduplicates the fiscal invoice before committing any financial records.
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(841650722)")):
        return {"processed": 0}
    now = datetime.now(timezone.utc)
    meta = AADEDocument.raw["_catalog_cost"]
    imported = exists(select(SupplierDocument.id).where(or_(
        SupplierDocument.aade_document_id == AADEDocument.id,
        SupplierDocument.identity_key == func.concat("aade:", Supplier.vat_number, ":", AADEDocument.mark),
    )))
    partial = exists(select(SupplierDocument.id).where(
        SupplierDocument.identity_key == func.concat("aade:", Supplier.vat_number, ":", AADEDocument.mark),
        SupplierDocument.raw_metadata["aade_partial"].astext == "true"))
    legacy = exists(select(SupplierDocument.id).where(
        SupplierDocument.identity_key == func.concat("aade:", Supplier.vat_number, ":", AADEDocument.mark),
        SupplierDocument.raw_metadata["aade_source_digest"].astext.is_not(None),
        SupplierDocument.raw_metadata["aade_source_digest_version"].astext.is_distinct_from("2")))
    matching_version = case(*[(Supplier.vat_number == vat, rule["revision"])
        for vat, rule in DIRECT_SKU_SUPPLIERS.items()], else_="line-costs-v2:")
    revision = func.concat(matching_version, policy.get("cost_refresh_requested_at", ""), ":",
                           func.coalesce(SupplierCatalogFeed.last_synced_at.cast(String), ""))
    candidate = db.execute(select(AADEDocument, Supplier)
        .join(Supplier, or_(AADEDocument.issuer_vat == Supplier.vat_number,
                           AADEDocument.issuer_vat == func.concat("EL", Supplier.vat_number)))
        .outerjoin(SupplierCatalogFeed, SupplierCatalogFeed.code == Supplier.code).where(
            or_(SupplierCatalogFeed.is_enabled.is_(True), and_(SupplierCatalogFeed.id.is_(None),
                Supplier.vat_number.in_(DIRECT_SKU_SUPPLIERS))), Supplier.vat_number.is_not(None),
            AADEDocument.document_direction == "expense", AADEDocument.invoice_type.in_(["1.1", "1.2", "1.3"]),
            AADEDocument.issue_date <= date.today(), AADEDocument.is_cancelled.is_(False),
            AADEDocument.cancelled_by_mark.is_(None),
            or_(~imported, partial, legacy, meta["status"].astext.is_(None), meta["status"].astext == "review"),
            func.coalesce(AADEDocument.raw["record_type"].astext, "full_document") == "full_document",
            or_(meta["input_revision"].astext.is_distinct_from(revision),
                meta["next_attempt_at"].astext.is_(None), meta["next_attempt_at"].astext <= now.isoformat()),
        ).add_columns(revision.label("input_revision"))
        .order_by(AADEDocument.issue_date.desc(), AADEDocument.id).limit(1)).first()
    if not candidate:
        db.rollback()
        return {"processed": 0}
    document, supplier, input_revision = candidate
    document_id = document.id
    confirmed = str(supplier.id) in policy.get("piece_supplier_ids", [])
    result = {"status": "review", "next_attempt_at": (now + timedelta(hours=6)).isoformat(),
              "input_revision": input_revision}
    costs_created = 0
    try:
        preview = invoice_preview(db, document_id, supplier.id, confirm_missing_units=confirmed)
        if preview["can_import"]:
            accepted = accept_invoice(db, document_id, SupplierAADEAcceptRequest(
                supplier_id=supplier.id, fingerprint=preview["fingerprint"],
                confirm_products_and_units=True, confirm_missing_units=confirmed), actor, automated=True)
            costs_created = accepted["costs_created"]
            result["status"] = "partial" if accepted.get("pending_lines") else "imported"
        result["pending_lines"] = preview["pending_lines"]
        if preview["imported"] and not preview["reasons"]:
            result["status"] = "partial" if preview["pending_lines"] else "imported"
            upgrade_source_digest(db, document_id)
        result["reasons"] = preview["reasons"] + list(dict.fromkeys(reason for line in preview["lines"] for reason in line["reasons"]))
    except (ValueError, IntegrityError):
        db.rollback()
        result["reasons"] = ["Invoice requires review; no automatic cost was saved."]
    current = db.get(AADEDocument, document_id)
    raw = current.raw
    if detail_info(raw)["status"] == "verified":
        raw = {**raw, META_KEY: {**raw[META_KEY], "source_hash": source_fingerprint(raw)}}
    current.raw = {**raw, "_catalog_cost": {**result, "checked_at": now.isoformat()}}
    db.commit()
    return {"processed": 1, "costs_created": costs_created, "status": result["status"]}


def process_aade_cost_batch(db, limit=5):
    """Drain a small batch; leave CPU and database capacity for reports."""
    processed = costs = 0
    for _ in range(min(max(limit, 1), 5)):
        result = process_aade_costs(db)
        if not result["processed"]:
            break
        processed += 1
        costs += result["costs_created"]
    return {"processed": processed, "costs_created": costs}
