import re
from datetime import datetime, timezone

from sqlalchemy import func, select, text

from app.models import AADEDocument, IntegrationSetting, Supplier, SupplierCatalogFeed, SupplierDocument

PARTY_NAME_KEYS = ("name", "legalName", "companyName", "businessName", "fullName", "partyName",
                   "traderName", "description", "denomination", "eponymia")
PARTY_DIRECT_KEYS = tuple(f"{prefix}{suffix}" for prefix in ("issuer", "counterpart", "counterparty", "counter")
                          for suffix in ("Name", "_name", "LegalName", "CompanyName", "BusinessName", "FullName", "Description"))


def _pick(row, *keys):
    if not isinstance(row, dict):
        return None
    lowered = {str(key).lower(): value for key, value in row.items()}
    return next((lowered[key.lower()] for key in keys if lowered.get(key.lower()) not in (None, "")), None)


def aade_party_name(raw, party):
    header = _pick(raw, "invoiceHeader", "header") or {}
    party_data = _pick(raw, party) or _pick(header, party) or {}
    prefixes = (party,) if party != "counterpart" else ("counterpart", "counterparty", "counter")
    direct = [key for key in PARTY_DIRECT_KEYS if any(key.lower().startswith(prefix.lower()) for prefix in prefixes)]
    for value in (_pick(party_data, *PARTY_NAME_KEYS), _pick(raw, *direct), _pick(header, *direct)):
        if value is not None and not isinstance(value, (dict, list, bool)) and str(value).strip():
            return str(value).strip()
    return None


def fiscal_supplier_vat(value, raw):
    vat = normalize_vat(value)
    party = "counterpart" if raw.get("record_type") == "book_info" else "issuer"
    header = _pick(raw, "invoiceHeader", "header") or {}
    data = _pick(raw, party) or _pick(header, party) or {}
    country = str(_pick(data, "country") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", country) and country not in {"GR", "EL"} and not vat.startswith(country):
        if re.match(r"[A-Z]{2}", vat):
            return ""
        vat = country + vat if vat else ""
    return vat


def valid_supplier_vat(vat):
    return (bool(re.fullmatch(r"(?:[0-9]{9}|[A-Z]{2}[A-Z0-9]{2,30})", vat))
            and bool(re.search(r"[0-9]", vat))
            and bool(re.search(r"[1-9A-Z]", vat[2:] if vat[:2].isalpha() else vat)))


def _identity_data(row):
    return {"id": str(row.id), "code": row.code, "name": row.name, "vat_number": row.vat_number}


def normalize_vat(value):
    value = re.sub(r"\s+", "", str(value or "")).upper()
    if value.startswith("EL"):
        value = value[2:]
    return value


def supplier_identities(db):
    suppliers = db.scalars(select(Supplier).order_by(Supplier.name)).all()
    feeds = db.execute(select(SupplierCatalogFeed.code, SupplierCatalogFeed.name)).all()
    rows = [_identity_data(row) for row in suppliers]
    codes = {row.code for row in suppliers}
    return rows + [{"id": None, "code": code, "name": name, "vat_number": None} for code, name in feeds if code not in codes]


def save_supplier_identity(db, payload, user):
    # A shared lock prevents two supplier codes claiming one VAT concurrently.
    db.execute(text("SELECT pg_advisory_xact_lock(841650721)"))
    code = payload.code.upper()
    vat = normalize_vat(payload.vat_number)
    if not valid_supplier_vat(vat):
        raise ValueError("Enter the supplier's 9-digit Greek AFM or country-prefixed foreign VAT number.")
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
    supplier.raw_metadata = {**(supplier.raw_metadata or {}), "identity_audit": audit, "name_pending": False}
    supplier.name, supplier.vat_number = payload.name, vat
    db.commit()
    return _identity_data(supplier)


def aade_supplier_registry(db, start, end):
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "aade"))
    own = normalize_vat((integration.config or {}).get("vat_number")) if integration else ""
    if not re.fullmatch(r"[0-9]{9}", own) or own == "000000000":
        raise ValueError("Configure the INDE AFM in AADE settings first.")
    # Expand raw once per invoice: repeated JSON lookups repeatedly decompress TOAST data.
    keys = ("record_type", "issuer", "counterpart", "invoiceHeader", "header", *PARTY_DIRECT_KEYS)
    fields = func.jsonb_each(AADEDocument.raw).table_valued("key", "value").alias("party_fields")
    identity_json = select(func.jsonb_object_agg(func.lower(fields.c.key), fields.c.value))\
        .select_from(fields).where(func.lower(fields.c.key).in_({key.lower() for key in keys}))\
        .correlate(AADEDocument).scalar_subquery()
    query = select(AADEDocument.id, AADEDocument.issuer_vat, AADEDocument.counterpart_vat,
                   AADEDocument.mark, AADEDocument.issue_date, identity_json.label("identity"))\
        .where(AADEDocument.document_direction == "expense").execution_options(yield_per=500)
    discovered, skipped = {}, set()
    for row in db.execute(query):
        raw = row.identity or {}
        vat = fiscal_supplier_vat(row.issuer_vat, raw)
        if normalize_vat(row.counterpart_vat) != own or vat == own:
            skipped.add(row.id)
            continue
        if not valid_supplier_vat(vat) or raw.get("record_type") in {"cancellation", "vat_info"}:
            skipped.add(row.id)
            continue
        group = discovered.setdefault(vat, {"names": {}, "documents": set(), "period_documents": set(), "last_document_date": row.issue_date})
        name = aade_party_name(raw, "counterpart" if raw.get("record_type") == "book_info" else "issuer")
        if name:
            group["names"].setdefault(" ".join(name.split()).casefold(), name[:255])
        key = str(row.mark or row.id)
        group["documents"].add(key)
        if start <= row.issue_date <= end:
            group["period_documents"].add(key)
        group["last_document_date"] = max(group["last_document_date"], row.issue_date)
    registered = {}
    for supplier in db.scalars(select(Supplier).order_by(Supplier.name)):
        if supplier.vat_number:
            registered.setdefault(normalize_vat(supplier.vat_number), []).append(supplier)
    rows = []
    for vat in sorted(discovered.keys() | registered.keys()):
        group = discovered.get(vat, {})
        matches = registered.get(vat, [])
        supplier = matches[0] if len(matches) == 1 else None
        names = group.get("names", {})
        source_name = next(iter(names.values())) if len(names) == 1 else None
        metadata = (supplier.raw_metadata or {}) if supplier else {}
        pending = metadata.get("name_pending", False) if supplier else source_name is None
        rows.append({"id": str(supplier.id) if supplier else None, "code": supplier.code if supplier else None,
                     "vat_number": vat, "name": supplier.name if supplier else source_name or f"AFM {vat}",
                     "name_pending": pending, "aade_name": source_name, "identity_conflict": len(matches) > 1,
                     "source": "AADE" if metadata.get("aade_discovered") or not supplier else "Registered",
                     "documents": len(group.get("documents", [])), "period_documents": len(group.get("period_documents", [])),
                     "last_document_date": group.get("last_document_date")})
    return {"rows": rows, "skipped_records": len(skipped)}


def import_aade_suppliers(db, user):
    db.execute(text("SELECT pg_advisory_xact_lock(841650721)"))
    registry = aade_supplier_registry(db, datetime.min.date(), datetime.max.date())
    created, existing, updated, conflicts = 0, 0, 0, 0
    for row in registry["rows"]:
        if not row["documents"]:
            continue
        if row["identity_conflict"]:
            conflicts += 1
            continue
        if row["id"]:
            existing += 1
            supplier = db.get(Supplier, row["id"], with_for_update=True)
            metadata = supplier.raw_metadata or {}
            if metadata.get("aade_discovered") and metadata.get("name_pending") and row["aade_name"]:
                supplier.name = row["aade_name"]
                supplier.raw_metadata = {**metadata, "name_pending": False}
                updated += 1
            continue
        code = "AADE_" + row["vat_number"]
        if db.scalar(select(Supplier.id).where(Supplier.code == code)):
            conflicts += 1
            continue
        db.add(Supplier(code=code, name=row["name"], vat_number=row["vat_number"], raw_metadata={
            "aade_discovered": True, "name_pending": row["name_pending"],
            "identity_audit": [{"source": "stored_aade_expenses", "user_id": str(user.id),
                                "at": datetime.now(timezone.utc).isoformat(), "name": row["name"], "vat_number": row["vat_number"]}]}))
        created += 1
    db.commit()
    return {"created": created, "existing": existing, "names_updated": updated,
            "conflicts": conflicts, "skipped_records": registry["skipped_records"]}


def registered_supplier_names(db):
    grouped = {}
    for name, vat in db.execute(select(Supplier.name, Supplier.vat_number)):
        if vat:
            grouped.setdefault(normalize_vat(vat), []).append(name)
    return {vat: names[0] for vat, names in grouped.items() if len(names) == 1}
