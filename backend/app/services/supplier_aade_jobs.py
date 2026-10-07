"""One invoice per background tick, using the same reviewed import guards."""

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.models import AADEDocument, Supplier, SupplierCatalogFeed, SupplierDocument, User
from app.schemas.suppliers import SupplierAADEAcceptRequest
from app.services.supplier_aade_costs import accept_invoice, invoice_preview
from app.services.supplier_catalog_settings import pricing_settings


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
    candidate = db.execute(select(AADEDocument, Supplier)
        .join(Supplier, or_(AADEDocument.issuer_vat == Supplier.vat_number,
                           AADEDocument.issuer_vat == func.concat("EL", Supplier.vat_number)))
        .join(SupplierCatalogFeed, SupplierCatalogFeed.code == Supplier.code).where(
            SupplierCatalogFeed.is_enabled.is_(True), Supplier.vat_number.is_not(None),
            AADEDocument.document_direction == "expense", AADEDocument.invoice_type.in_(["1.1", "1.2", "1.3"]),
            AADEDocument.issue_date <= date.today(), AADEDocument.is_cancelled.is_(False),
            AADEDocument.cancelled_by_mark.is_(None), ~imported,
            func.coalesce(AADEDocument.raw["record_type"].astext, "full_document") == "full_document",
            or_(meta["next_attempt_at"].astext.is_(None), meta["next_attempt_at"].astext <= now.isoformat()),
        ).order_by(AADEDocument.issue_date.desc(), AADEDocument.id).limit(1)).first()
    if not candidate:
        db.rollback()
        return {"processed": 0}
    document, supplier = candidate
    document_id = document.id
    confirmed = str(supplier.id) in policy.get("piece_supplier_ids", [])
    result = {"status": "review", "next_attempt_at": (now + timedelta(hours=6)).isoformat()}
    costs_created = 0
    try:
        preview = invoice_preview(db, document_id, supplier.id, confirm_missing_units=confirmed)
        if preview["can_import"]:
            accepted = accept_invoice(db, document_id, SupplierAADEAcceptRequest(
                supplier_id=supplier.id, fingerprint=preview["fingerprint"],
                confirm_products_and_units=True, confirm_missing_units=confirmed), actor, automated=True)
            costs_created = accepted["costs_created"]
            result["status"] = "imported"
        else:
            result["reasons"] = preview["reasons"] + list(dict.fromkeys(reason for line in preview["lines"] for reason in line["reasons"]))
    except (ValueError, IntegrityError):
        db.rollback()
        result["reasons"] = ["Invoice requires review; no automatic cost was saved."]
    current = db.get(AADEDocument, document_id)
    current.raw = {**current.raw, "_catalog_cost": {**result, "checked_at": now.isoformat()}}
    db.commit()
    return {"processed": 1, "costs_created": costs_created, "status": result["status"]}
