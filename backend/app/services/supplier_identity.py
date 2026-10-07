import re
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.models import Supplier, SupplierCatalogFeed, SupplierDocument


def normalize_vat(value):
    value = re.sub(r"\s+", "", str(value or "")).upper()
    if value.startswith("EL"):
        value = value[2:]
    return value


def supplier_identities(db):
    suppliers = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    feeds = db.execute(select(SupplierCatalogFeed.code, SupplierCatalogFeed.name)).all()
    rows = [{"id": str(row.id), "code": row.code, "name": row.name, "vat_number": row.vat_number} for row in suppliers]
    codes = {row.code for row in suppliers}
    return rows + [{"id": None, "code": code, "name": name, "vat_number": None} for code, name in feeds if code not in codes]


def save_supplier_identity(db, payload, user):
    # A shared lock prevents two supplier codes claiming one VAT concurrently.
    db.execute(text("SELECT pg_advisory_xact_lock(841650721)"))
    code = payload.code.upper()
    vat = normalize_vat(payload.vat_number)
    if not re.fullmatch(r"[0-9]{9}", vat) or vat == "000000000":
        raise ValueError("Enter the supplier's 9-digit Greek AFM.")
    supplier = db.scalar(select(Supplier).where(Supplier.code == code).with_for_update())
    others = db.execute(select(Supplier.code, Supplier.vat_number).where(Supplier.code != code)).all()
    if any(normalize_vat(number) == vat for _, number in others):
        raise ValueError("This AFM is already assigned to another supplier.")
    if supplier and supplier.vat_number and normalize_vat(supplier.vat_number) != vat:
        if db.scalar(select(SupplierDocument.id).where(SupplierDocument.supplier_id == supplier.id,
                                                      SupplierDocument.aade_document_id.is_not(None)).limit(1)):
            raise ValueError("This supplier has linked AADE invoices; review them before changing AFM.")
    if supplier is None:
        supplier = Supplier(code=code, name=payload.name)
        db.add(supplier)
    audit = list((supplier.raw_metadata or {}).get("identity_audit", []))
    audit.append({"user_id": str(user.id), "at": datetime.now(timezone.utc).isoformat(),
                  "previous_name": supplier.name, "previous_vat": supplier.vat_number,
                  "name": payload.name, "vat_number": vat})
    supplier.raw_metadata = {**(supplier.raw_metadata or {}), "identity_audit": audit}
    supplier.name, supplier.vat_number = payload.name, vat
    db.commit()
    return {"id": str(supplier.id), "code": supplier.code, "name": supplier.name, "vat_number": supplier.vat_number}


def registered_supplier_names(db):
    grouped = {}
    for name, vat in db.execute(select(Supplier.name, Supplier.vat_number)):
        if vat:
            grouped.setdefault(normalize_vat(vat), []).append(name)
    return {vat: names[0] for vat, names in grouped.items() if len(names) == 1}
