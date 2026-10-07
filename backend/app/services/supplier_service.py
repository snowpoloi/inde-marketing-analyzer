from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import (
    AADEDocument,
    OpenCartOrder,
    OpenCartOrderProduct,
    ProductCatalog,
    Supplier,
    SupplierDocument,
    SupplierDocumentLine,
    SupplierImportBatch,
    SupplierProductCost,
    SupplierProductMap,
    SupplierShippingCost,
    User,
)
from app.schemas.suppliers import ManualSupplierCostRequest, SupplierImportRequest, VerifySupplierMappingRequest
from app.services.parsing import dec_to_float
from app.services.product_sales_costing import allocate_coupon, flag, net_product_sale, present
from app.services.supplier_aade_costs import validated_cost_rows, validated_documents
from app.services.supplier_costing import (
    CatalogIdentity,
    CostOption,
    MatchCandidate,
    calculate_purchase_line,
    decimal_value,
    exact_catalog_matches,
    fuzzy_catalog_candidates,
    margin_metrics,
    money,
    normalize_identifier,
    normalize_name,
    select_cost_as_of,
    supplier_mapping_identity,
)


def _supplier_code(value: str) -> str:
    return normalize_name(value).replace(" ", "_").upper()


def _canonical_hash(payload: SupplierImportRequest) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _document_identity(supplier: Supplier, document: Any) -> str:
    number = normalize_identifier(document.document_number or document.supplier_order_id)
    if number:
        return f"{supplier.code}|{document.document_type}|{document.document_date.isoformat()}|{number}"
    raw = json.dumps(document.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return f"{supplier.code}|{document.document_type}|{document.document_date.isoformat()}|sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _catalog_identity(product: ProductCatalog) -> CatalogIdentity:
    raw = product.raw if isinstance(product.raw, dict) else {}
    return CatalogIdentity(
        key=str(product.id),
        sku=product.sku,
        model=product.model,
        product_id=product.product_id,
        ean=product.ean or raw.get("ean") or raw.get("gtin"),
        upc=product.upc or raw.get("upc"),
        mpn=product.mpn or raw.get("mpn"),
        name=product.name,
        manufacturer=product.manufacturer or product.brand,
    )


def _catalog_data(db: Session) -> tuple[list[CatalogIdentity], dict[str, ProductCatalog]]:
    products = list(db.scalars(select(ProductCatalog)).all())
    return [_catalog_identity(product) for product in products], {str(product.id): product for product in products}


def _upsert_supplier(db: Session, payload: Any) -> Supplier:
    code = _supplier_code(payload.code)
    supplier = db.scalar(select(Supplier).where(Supplier.code == code))
    if supplier is None:
        supplier = Supplier(code=code, name=payload.name)
        db.add(supplier)
        db.flush()
    supplier.name = payload.name
    supplier.vat_number = payload.vat_number or supplier.vat_number
    supplier.aliases = payload.aliases or supplier.aliases
    supplier.default_currency = payload.default_currency.upper()
    if "free_shipping_threshold" in payload.model_fields_set:
        supplier.free_shipping_threshold = payload.free_shipping_threshold
    if "payment_terms_days" in payload.model_fields_set:
        supplier.payment_terms_days = payload.payment_terms_days
    supplier.raw_metadata = {**(supplier.raw_metadata or {}), **{key: value for key, value in payload.raw_metadata.items() if key != "settings_audit"}}
    return supplier


def _set_catalog_mapping(mapping: SupplierProductMap, catalog: ProductCatalog, candidate: MatchCandidate) -> None:
    mapping.product_catalog_id = catalog.id
    mapping.opencart_product_id = catalog.product_id
    mapping.opencart_sku = catalog.sku
    mapping.opencart_model = catalog.model
    mapping.product_name = catalog.name
    mapping.match_method = candidate.method
    mapping.confidence = candidate.confidence
    mapping.status = "matched"


def _upsert_product_mapping(
    db: Session,
    *,
    supplier: Supplier,
    line: Any,
    catalogs: list[CatalogIdentity],
    catalog_by_id: dict[str, ProductCatalog],
    identity_context: str,
) -> SupplierProductMap:
    identity_key = supplier_mapping_identity(line.supplier_sku, line.supplier_ean, line.supplier_code, line.description)
    if not any((line.supplier_sku, line.supplier_ean, line.supplier_code)):
        # Description-only review is scoped to this document line, never a reusable auto-match.
        identity_key += "|source:" + hashlib.sha256(identity_context.encode()).hexdigest()
    mapping = db.scalar(
        select(SupplierProductMap).where(
            SupplierProductMap.supplier_id == supplier.id,
            SupplierProductMap.identity_key == identity_key,
        )
    )
    now = datetime.now(timezone.utc)
    if mapping is None:
        mapping = SupplierProductMap(
            supplier_id=supplier.id,
            identity_key=identity_key,
            supplier_code=line.supplier_code,
            supplier_sku=line.supplier_sku,
            supplier_ean=line.supplier_ean,
            product_name=(line.description or "")[:500] or None,
            purchase_unit=line.unit,
            sales_unit=line.sales_unit,
            pack_quantity=line.pack_quantity,
            conversion_factor=line.conversion_factor,
            first_seen_at=now,
            last_seen_at=now,
            raw_metadata=line.raw_metadata,
        )
        db.add(mapping)
        db.flush()
    else:
        if line.unit and mapping.purchase_unit and normalize_identifier(line.unit) != normalize_identifier(mapping.purchase_unit):
            raise ValueError("Supplier purchase unit changed; review the mapping before importing.")
        if "conversion_factor" in line.model_fields_set and mapping.conversion_factor != line.conversion_factor:
            raise ValueError("Supplier unit conversion changed; verify the mapping before importing.")
        mapping.supplier_code = line.supplier_code or mapping.supplier_code
        mapping.supplier_sku = line.supplier_sku or mapping.supplier_sku
        mapping.supplier_ean = line.supplier_ean or mapping.supplier_ean
        mapping.product_name = line.description[:500] if line.description else mapping.product_name
        mapping.last_seen_at = now
        mapping.raw_metadata = {**(mapping.raw_metadata or {}), **{key: value for key, value in line.raw_metadata.items() if key != "verification_audit"}}

    if mapping.verified and mapping.product_catalog_id is None:
        raise ValueError("Verified product is no longer available; review the mapping before importing.")
    if mapping.verified and mapping.product_catalog_id:
        mapping.status = "matched"
        mapping.match_method = "verified"
        mapping.confidence = Decimal("1")
        return mapping

    exact = exact_catalog_matches(
        catalogs,
        supplier=supplier.code,
        supplier_sku=line.supplier_sku,
        supplier_ean=line.supplier_ean,
        supplier_code=line.supplier_code,
    )
    if len(exact) == 1:
        catalog = catalog_by_id[exact[0].catalog.key]
        _set_catalog_mapping(mapping, catalog, exact[0])
    elif len(exact) > 1:
        if mapping.product_catalog_id:
            raise ValueError("Existing mapping conflicts with new identifiers. Verify it manually before importing.")
        mapping.status = "review"
        mapping.match_method = "ambiguous_exact"
        mapping.confidence = exact[0].confidence
    else:
        if mapping.product_catalog_id:
            raise ValueError("Existing mapping no longer matches the catalog. Verify it manually before importing.")
        mapping.status = "unmatched"
        mapping.match_method = "unmatched"
        mapping.confidence = Decimal("0")
    return mapping


def _match_aade_document(db: Session, supplier: Supplier, document_date: date, gross_total: Decimal, document_number: str | None):
    if not supplier.vat_number or gross_total == 0:
        return None
    candidates = list(
        db.scalars(
            select(AADEDocument).where(
                AADEDocument.issuer_vat == supplier.vat_number,
                AADEDocument.document_direction == "expense",
                AADEDocument.is_cancelled.is_(False),
                AADEDocument.issue_date == document_date,
                AADEDocument.gross_value == abs(gross_total),
            )
        ).all()
    )
    target = normalize_identifier(document_number)
    if target:
        exact = [
            candidate
            for candidate in candidates
            if target
            in {
                normalize_identifier(candidate.aa),
                normalize_identifier(f"{candidate.series or ''}{candidate.aa or ''}"),
                normalize_identifier(f"{candidate.series or ''}/{candidate.aa or ''}"),
            }
        ]
        if len(exact) == 1:
            return exact[0]
    return None


def _cost_source_key(document: SupplierDocument, line: SupplierDocumentLine, mapping: SupplierProductMap) -> str:
    revision = f"{mapping.product_catalog_id}:{decimal_value(mapping.conversion_factor).normalize()}"
    digest = hashlib.sha256(revision.encode()).hexdigest()[:16]
    return f"{document.identity_key}|line:{line.line_number}|map:{mapping.id}|{digest}"


def _create_cost_from_line(
    db: Session,
    *,
    supplier: Supplier,
    document: SupplierDocument,
    line: SupplierDocumentLine,
    mapping: SupplierProductMap,
) -> SupplierProductCost | None:
    if mapping.product_catalog_id is None or line.line_type != "product" or line.quantity <= 0:
        return None
    source_key = _cost_source_key(document, line, mapping)
    existing = db.scalar(select(SupplierProductCost).where(SupplierProductCost.source_key == source_key))
    if existing:
        return existing
    _, unit_cost = calculate_purchase_line(
        quantity=line.quantity,
        unit_price_before_discount=line.unit_price_before_discount,
        discount_percent=line.discount_percent,
        discount_amount=line.discount_amount,
        net_line_total=line.net_line_total,
        conversion_factor=mapping.conversion_factor,
    )
    status = "credit" if document.document_type == "credit_note" else "active"
    cost = SupplierProductCost(
        supplier_id=supplier.id,
        supplier_product_map_id=mapping.id,
        product_catalog_id=mapping.product_catalog_id,
        source_line_id=line.id,
        supplier_sku=mapping.supplier_sku,
        source_type=document.document_type,
        source_reference=document.identity_key,
        source_key=source_key,
        supplier_order_id=document.supplier_order_id,
        supplier_invoice_number=document.document_number,
        purchase_date=document.document_date,
        quantity=line.quantity,
        unit_price_before_discount=line.unit_price_before_discount,
        discount_percent=line.discount_percent,
        net_unit_cost=unit_cost,
        net_line_total=line.net_line_total,
        vat=line.vat_amount,
        gross_total=line.gross_total,
        currency=document.currency,
        source_confidence=mapping.confidence,
        status=status,
        raw_metadata=line.raw_metadata,
    )
    db.add(cost)
    return cost


def _create_shipping_cost(
    db: Session,
    *,
    supplier: Supplier,
    document: SupplierDocument,
    line: SupplierDocumentLine,
    source_payload: Any,
) -> SupplierShippingCost:
    source_key = f"{document.identity_key}|shipping:{line.line_number}"
    existing = db.scalar(select(SupplierShippingCost).where(SupplierShippingCost.source_key == source_key))
    if existing:
        return existing
    shipping = SupplierShippingCost(
        supplier_id=supplier.id,
        document_id=document.id,
        source_line_id=line.id,
        source_key=source_key,
        supplier_order_id=document.supplier_order_id,
        invoice_reference=document.document_number,
        date=document.document_date,
        shipping_type=source_payload.shipping_type,
        net_shipping_cost=line.net_line_total,
        vat=line.vat_amount,
        gross_shipping_cost=line.gross_total,
        order_net_purchase_value=document.net_products_total,
        cbm=source_payload.cbm,
        weight=source_payload.weight,
        notes=source_payload.notes,
        raw_metadata=line.raw_metadata,
    )
    db.add(shipping)
    return shipping


def import_supplier_documents(db: Session, payload: SupplierImportRequest, user_id: UUID | None = None, *, commit: bool = True) -> dict[str, Any]:
    # Serialize imports for one supplier across workers, before checking identities.
    lock_key = int.from_bytes(hashlib.sha256(_supplier_code(payload.supplier.code).encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    content_hash = _canonical_hash(payload)
    existing_batch = db.scalar(
        select(SupplierImportBatch).where(SupplierImportBatch.content_hash == content_hash)
    )
    if existing_batch:
        return {
            "batch_id": str(existing_batch.id),
            "duplicate": True,
            "documents_imported": 0,
            "documents_skipped": len(payload.documents),
            "product_lines": 0,
            "matched_lines": 0,
            "unmatched_lines": 0,
            "shipping_lines": 0,
        }

    supplier = _upsert_supplier(db, payload.supplier)
    batch = SupplierImportBatch(
        supplier_id=supplier.id,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        filename=payload.filename,
        content_hash=content_hash,
        status="processing",
        raw_metadata={**payload.raw_metadata, "imported_by": str(user_id) if user_id else None},
    )
    db.add(batch)
    db.flush()

    catalogs, catalog_by_id = _catalog_data(db)
    imported = skipped = product_lines = matched = unmatched = shipping_lines = 0
    for source_document in payload.documents:
        identity_key = _document_identity(supplier, source_document)
        document_hash = hashlib.sha256(json.dumps(source_document.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        existing_document = db.scalar(select(SupplierDocument).where(SupplierDocument.identity_key == identity_key))
        if existing_document:
            if (existing_document.raw_metadata or {}).get("import_hash") != document_hash:
                raise ValueError(f"Document {source_document.document_number} already exists with different content. Manual review required.")
            skipped += 1
            continue

        document = SupplierDocument(
            supplier_id=supplier.id,
            import_batch_id=batch.id,
            identity_key=identity_key,
            document_type=source_document.document_type,
            document_number=source_document.document_number,
            document_date=source_document.document_date,
            supplier_order_id=source_document.supplier_order_id,
            currency=source_document.currency.upper(),
            raw_metadata={**source_document.raw_metadata, "import_hash": document_hash},
        )
        db.add(document)
        db.flush()

        calculated_products = calculated_shipping = calculated_other = calculated_vat = calculated_gross = Decimal("0")
        staged_lines: list[tuple[SupplierDocumentLine, Any, SupplierProductMap | None]] = []
        for index, source_line in enumerate(source_document.lines, start=1):
            mapping = None
            conversion_factor = source_line.conversion_factor
            if source_line.line_type == "product":
                mapping = _upsert_product_mapping(
                    db,
                    supplier=supplier,
                    line=source_line,
                    catalogs=catalogs,
                    catalog_by_id=catalog_by_id,
                    identity_context=f"{identity_key}|line:{source_line.line_number or index}",
                )
                conversion_factor = mapping.conversion_factor
                product_lines += 1
                if mapping.product_catalog_id:
                    matched += 1
                else:
                    unmatched += 1

            net_total, net_unit_cost = calculate_purchase_line(
                quantity=source_line.quantity,
                unit_price_before_discount=source_line.unit_price_before_discount,
                discount_percent=source_line.discount_percent,
                discount_amount=source_line.discount_amount,
                net_line_total=source_line.net_line_total,
                conversion_factor=conversion_factor,
            )
            if source_document.document_type != "credit_note" and source_line.line_type == "product" and net_total < 0:
                raise ValueError("Product net totals cannot be negative outside credit notes.")
            vat_amount = money(source_line.vat_amount if source_line.vat_amount is not None else net_total * source_line.vat_rate / 100)
            gross_total = money(source_line.gross_total if source_line.gross_total is not None else net_total + vat_amount)
            if abs(gross_total - net_total - vat_amount) > Decimal("0.02"):
                raise ValueError(f"Line {index}: gross must equal net plus VAT.")
            if source_document.document_type == "credit_note":
                net_total = -abs(net_total)
                net_unit_cost = -abs(net_unit_cost)
                vat_amount = -abs(vat_amount)
                gross_total = -abs(gross_total)

            line = SupplierDocumentLine(
                document_id=document.id,
                supplier_product_map_id=mapping.id if mapping else None,
                line_number=source_line.line_number or str(index),
                line_type=source_line.line_type,
                supplier_code=source_line.supplier_code,
                supplier_sku=source_line.supplier_sku,
                supplier_ean=source_line.supplier_ean,
                description=source_line.description,
                quantity=source_line.quantity,
                unit=source_line.unit,
                unit_price_before_discount=source_line.unit_price_before_discount,
                discount_percent=source_line.discount_percent,
                discount_amount=source_line.discount_amount,
                net_unit_cost=net_unit_cost,
                net_line_total=net_total,
                vat_rate=source_line.vat_rate,
                vat_amount=vat_amount,
                gross_total=gross_total,
                raw_metadata=source_line.raw_metadata,
            )
            db.add(line)
            db.flush()
            staged_lines.append((line, source_line, mapping))
            calculated_vat += vat_amount
            calculated_gross += gross_total
            if source_line.line_type == "product":
                calculated_products += net_total
            elif source_line.line_type == "shipping":
                calculated_shipping += net_total
                shipping_lines += 1
            else:
                calculated_other += net_total

        for field, calculated in (("net_products_total", calculated_products), ("net_shipping_total", calculated_shipping),
                                  ("net_other_total", calculated_other), ("vat_total", calculated_vat), ("gross_total", calculated_gross)):
            supplied = getattr(source_document, field)
            if supplied is not None:
                supplied = -abs(supplied) if source_document.document_type == "credit_note" else supplied
                if abs(supplied - calculated) > Decimal("0.02"):
                    raise ValueError(f"Document {source_document.document_number}: {field} does not reconcile with its lines.")
            setattr(document, field, money(calculated))
        if any(line.line_type == "discount" and line.net_line_total for line, _, _ in staged_lines):
            raise ValueError("Allocate product discounts to individual product lines before import; unallocated discounts cannot create reliable COGS.")
        aade_document = _match_aade_document(
            db,
            supplier,
            document.document_date,
            document.gross_total,
            document.document_number,
        )
        document.aade_document_id = aade_document.id if aade_document else None

        for line, source_line, mapping in staged_lines:
            if mapping:
                _create_cost_from_line(db, supplier=supplier, document=document, line=line, mapping=mapping)
            if line.line_type == "shipping":
                _create_shipping_cost(
                    db,
                    supplier=supplier,
                    document=document,
                    line=line,
                    source_payload=source_line,
                )
        imported += 1
        db.flush()

    batch.status = "completed"
    batch.imported_documents = imported
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "batch_id": str(batch.id),
        "duplicate": False,
        "documents_imported": imported,
        "documents_skipped": skipped,
        "product_lines": product_lines,
        "matched_lines": matched,
        "unmatched_lines": unmatched,
        "shipping_lines": shipping_lines,
    }


def _backfill_mapping_costs(db: Session, mapping: SupplierProductMap) -> int:
    if mapping.product_catalog_id is None:
        return 0
    rows = db.execute(
        select(SupplierDocumentLine, SupplierDocument, Supplier)
        .join(SupplierDocument, SupplierDocumentLine.document_id == SupplierDocument.id)
        .join(Supplier, SupplierDocument.supplier_id == Supplier.id)
        .where(SupplierDocumentLine.supplier_product_map_id == mapping.id)
    ).all()
    created = 0
    for line, document, supplier in rows:
        before = db.scalar(
            select(SupplierProductCost.id).where(
                SupplierProductCost.source_key == _cost_source_key(document, line, mapping)
            )
        )
        _create_cost_from_line(db, supplier=supplier, document=document, line=line, mapping=mapping)
        if before is None:
            created += 1
    return created


def verify_supplier_mapping(
    db: Session,
    mapping_id: UUID,
    payload: VerifySupplierMappingRequest,
    user: User,
) -> dict[str, Any]:
    mapping = db.get(SupplierProductMap, mapping_id)
    catalog = db.get(ProductCatalog, payload.product_catalog_id)
    if mapping is None or catalog is None:
        raise ValueError("Supplier mapping or OpenCart product was not found.")
    db.refresh(mapping, with_for_update=True)
    old_catalog = mapping.product_catalog_id
    old_factor = mapping.conversion_factor
    changed = old_catalog != catalog.id or old_factor != payload.conversion_factor
    audit = list((mapping.raw_metadata or {}).get("verification_audit", []))
    audit.append({"at": datetime.now(timezone.utc).isoformat(), "user_id": str(user.id),
                  "previous_product": str(old_catalog) if old_catalog else None, "previous_factor": str(old_factor),
                  "product": str(catalog.id), "factor": str(payload.conversion_factor)})
    mapping.raw_metadata = {**(mapping.raw_metadata or {}), "verification_audit": audit}
    if changed:
        for cost in db.scalars(select(SupplierProductCost).where(SupplierProductCost.supplier_product_map_id == mapping.id, SupplierProductCost.status == "active")).all():
            if cost.source_line_id is None:
                raise ValueError("Mapping has manual costs; create a separate mapping or review those costs before changing the product/unit.")
            cost.status = "superseded"
    mapping.product_catalog_id = catalog.id
    mapping.opencart_product_id = catalog.product_id
    mapping.opencart_sku = catalog.sku
    mapping.opencart_model = catalog.model
    mapping.product_name = catalog.name
    mapping.purchase_unit = payload.purchase_unit or mapping.purchase_unit
    mapping.sales_unit = payload.sales_unit or mapping.sales_unit
    mapping.pack_quantity = payload.pack_quantity
    mapping.conversion_factor = payload.conversion_factor
    mapping.match_method = "verified"
    mapping.confidence = Decimal("1")
    mapping.status = "matched"
    mapping.verified = True
    mapping.verified_by = user.id
    mapping.verified_at = datetime.now(timezone.utc)
    costs_created = _backfill_mapping_costs(db, mapping)
    db.commit()
    return {"mapping_id": str(mapping.id), "verified": True, "costs_created": costs_created}


def add_manual_cost(db: Session, payload: ManualSupplierCostRequest, user_id: UUID | None = None) -> dict[str, Any]:
    mapping = db.get(SupplierProductMap, payload.supplier_product_map_id, with_for_update=True, populate_existing=True)
    if mapping is None or mapping.supplier_id != payload.supplier_id or mapping.product_catalog_id is None or not mapping.verified:
        raise ValueError("A verified supplier product mapping is required before adding manual COGS.")
    reference = payload.source_reference or f"{payload.purchase_date.isoformat()}:{money(payload.net_unit_cost)}"
    source_key = f"manual:{mapping.id}:{payload.purchase_date.isoformat()}:{reference}"
    existing = db.scalar(select(SupplierProductCost).where(SupplierProductCost.source_key == source_key))
    if existing:
        if existing.net_unit_cost != money(payload.net_unit_cost) or existing.quantity != payload.quantity or existing.source_confidence != payload.source_confidence:
            raise ValueError("Manual cost reference already exists with a different price.")
        return {"cost_id": str(existing.id), "duplicate": True}
    quantity = decimal_value(payload.quantity)
    unit_cost = money(payload.net_unit_cost)
    cost = SupplierProductCost(
        supplier_id=payload.supplier_id,
        supplier_product_map_id=mapping.id,
        product_catalog_id=mapping.product_catalog_id,
        supplier_sku=mapping.supplier_sku,
        source_type="manual",
        source_reference=payload.source_reference,
        source_key=source_key,
        purchase_date=payload.purchase_date,
        quantity=quantity,
        unit_price_before_discount=unit_cost,
        net_unit_cost=unit_cost,
        net_line_total=money(quantity * unit_cost),
        gross_total=money(quantity * unit_cost),
        currency=payload.currency.upper(),
        source_confidence=payload.source_confidence,
        raw_metadata={**payload.raw_metadata, "created_by": str(user_id) if user_id else None},
    )
    db.add(cost)
    db.commit()
    return {"cost_id": str(cost.id), "duplicate": False}


def _cost_options(costs: list[SupplierProductCost]) -> list[CostOption]:
    return [
        CostOption(
            key=str(cost.id),
            purchase_date=cost.purchase_date,
            source_type=cost.source_type,
            net_unit_cost=cost.net_unit_cost,
            confidence=cost.source_confidence,
            status=cost.status,
        )
        for cost in costs if cost.currency == "EUR"
    ]


def _selected_cost(costs: list[SupplierProductCost], as_of: date) -> SupplierProductCost | None:
    option = select_cost_as_of(_cost_options(costs), as_of)
    if option is None:
        return None
    return next(cost for cost in costs if str(cost.id) == option.key)


def supplier_products(db: Session, as_of: date) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SupplierProductMap, Supplier, ProductCatalog)
        .join(Supplier, SupplierProductMap.supplier_id == Supplier.id)
        .outerjoin(ProductCatalog, SupplierProductMap.product_catalog_id == ProductCatalog.id)
        .order_by(Supplier.name, SupplierProductMap.product_name)
    ).all()
    costs_by_map: dict[UUID, list[SupplierProductCost]] = defaultdict(list)
    for cost in validated_cost_rows(db, db.scalars(select(SupplierProductCost).where(SupplierProductCost.purchase_date <= as_of)).all()):
        costs_by_map[cost.supplier_product_map_id].append(cost)

    results = []
    for mapping, supplier, catalog in rows:
        costs = costs_by_map.get(mapping.id, [])
        current = _selected_cost(costs, as_of)
        previous = None
        if current:
            previous = _selected_cost(costs, current.purchase_date.fromordinal(current.purchase_date.toordinal() - 1))
        change = None
        if current and previous and previous.net_unit_cost:
            change = (current.net_unit_cost - previous.net_unit_cost) / previous.net_unit_cost * Decimal("100")
        results.append(
            {
                "mapping_id": str(mapping.id),
                "supplier_id": str(supplier.id),
                "supplier": supplier.name,
                "supplier_sku": mapping.supplier_sku,
                "supplier_code": mapping.supplier_code,
                "supplier_ean": mapping.supplier_ean,
                "product_catalog_id": str(catalog.id) if catalog else None,
                "opencart_product_id": catalog.product_id if catalog else mapping.opencart_product_id,
                "opencart_sku": catalog.sku if catalog else mapping.opencart_sku,
                "opencart_model": catalog.model if catalog else mapping.opencart_model,
                "product_name": catalog.name if catalog else mapping.product_name,
                "current_cogs": dec_to_float(current.net_unit_cost) if current else None,
                "previous_cogs": dec_to_float(previous.net_unit_cost) if previous else None,
                "cost_change_percent": dec_to_float(change) if change is not None else None,
                "cost_source": current.source_type if current else None,
                "cost_reference": current.source_reference if current else None,
                "cost_date": current.purchase_date.isoformat() if current else None,
                "cost_confidence": dec_to_float(current.source_confidence) if current else None,
                "match_status": mapping.status,
                "match_method": mapping.match_method,
                "match_confidence": dec_to_float(mapping.confidence),
                "verified": mapping.verified,
                "conversion_factor": dec_to_float(mapping.conversion_factor),
            }
        )
    return results


def unmatched_products(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SupplierProductMap, Supplier)
        .join(Supplier, SupplierProductMap.supplier_id == Supplier.id)
        .where(or_(SupplierProductMap.product_catalog_id.is_(None), SupplierProductMap.status != "matched"))
        .order_by(Supplier.name, SupplierProductMap.product_name)
    ).all()
    if not rows:
        return []
    catalogs, catalog_by_id = _catalog_data(db)
    results = []
    for mapping, supplier in rows:
        exact = exact_catalog_matches(
            catalogs,
            supplier=supplier.code,
            supplier_sku=mapping.supplier_sku,
            supplier_ean=mapping.supplier_ean,
            supplier_code=mapping.supplier_code,
        )
        fuzzy = fuzzy_catalog_candidates(
            catalogs,
            description=mapping.product_name,
            manufacturer=(mapping.raw_metadata or {}).get("manufacturer"),
        )
        evidence = db.execute(select(SupplierDocumentLine, SupplierDocument)
            .join(SupplierDocument, SupplierDocumentLine.document_id == SupplierDocument.id)
            .where(SupplierDocumentLine.supplier_product_map_id == mapping.id)
            .order_by(SupplierDocument.document_date.desc(), SupplierDocumentLine.id).limit(20)).all()
        candidates: list[MatchCandidate] = []
        seen: set[str] = set()
        for candidate in [*exact, *fuzzy]:
            if candidate.catalog.key not in seen:
                candidates.append(candidate)
                seen.add(candidate.catalog.key)
        results.append(
            {
                "mapping_id": str(mapping.id),
                "supplier": supplier.name,
                "supplier_sku": mapping.supplier_sku,
                "supplier_code": mapping.supplier_code,
                "supplier_ean": mapping.supplier_ean,
                "description": mapping.product_name,
                "status": mapping.status,
                "reason": "Multiple exact products" if mapping.match_method == "ambiguous_exact" else "No unique exact match; name candidates require verification",
                "documents": [{"number": document.document_number, "date": document.document_date.isoformat(),
                               "type": document.document_type, "purchase_cost": dec_to_float(line.net_unit_cost),
                               "description": line.description} for line, document in evidence],
                "candidates": [
                    {
                        "product_catalog_id": candidate.catalog.key,
                        "product_id": catalog_by_id[candidate.catalog.key].product_id,
                        "sku": candidate.catalog.sku,
                        "model": candidate.catalog.model,
                        "name": candidate.catalog.name,
                        "method": candidate.method,
                        "confidence": dec_to_float(candidate.confidence),
                    }
                    for candidate in candidates[:5]
                ],
            }
        )
    return results


def supplier_performance(db: Session, date_from: date, date_to: date) -> list[dict[str, Any]]:
    suppliers = list(db.scalars(select(Supplier).order_by(Supplier.name)).all())
    documents = list(
        db.scalars(
            select(SupplierDocument).where(SupplierDocument.document_date.between(date_from, date_to))
        ).all()
    )
    shipping = list(
        db.scalars(select(SupplierShippingCost).join(SupplierDocument, SupplierShippingCost.document_id == SupplierDocument.id).where(
            SupplierShippingCost.date.between(date_from, date_to), SupplierDocument.document_type.in_(["invoice", "credit_note"])
        )).all()
    )
    documents = validated_documents(db, documents)
    valid_document_ids = {document.id for document in documents}
    shipping = [row for row in shipping if row.document_id in valid_document_ids]
    costs = list(
        validated_cost_rows(db, db.scalars(select(SupplierProductCost).where(SupplierProductCost.purchase_date <= date_to)).all())
    )
    docs_by_supplier: dict[UUID, list[SupplierDocument]] = defaultdict(list)
    shipping_by_supplier: dict[UUID, list[SupplierShippingCost]] = defaultdict(list)
    costs_by_map: dict[UUID, list[SupplierProductCost]] = defaultdict(list)
    for document in documents:
        if document.document_type in {"invoice", "credit_note"}:
            docs_by_supplier[document.supplier_id].append(document)
    for cost in shipping:
        shipping_by_supplier[cost.supplier_id].append(cost)
    for cost in costs:
        costs_by_map[cost.supplier_product_map_id].append(cost)

    mappings = list(db.scalars(select(SupplierProductMap)).all())
    catalog_ids = {mapping.product_catalog_id for mapping in mappings if mapping.product_catalog_id}
    catalog_by_id = {product.id: product for product in db.scalars(
        select(ProductCatalog).where(ProductCatalog.id.in_(catalog_ids))).all()} if catalog_ids else {}
    mappings_by_supplier: dict[UUID, list[SupplierProductMap]] = defaultdict(list)
    for mapping in mappings:
        mappings_by_supplier[mapping.supplier_id].append(mapping)

    rows = []
    for supplier in suppliers:
        supplier_docs = docs_by_supplier.get(supplier.id, [])
        supplier_shipping = shipping_by_supplier.get(supplier.id, [])
        purchases = sum((document.net_products_total for document in supplier_docs), Decimal("0"))
        freight = sum((cost.net_shipping_cost for cost in supplier_shipping), Decimal("0"))
        paid_shipping_docs = {cost.document_id for cost in supplier_shipping if cost.net_shipping_cost != 0}
        purchase_docs = [document for document in supplier_docs if document.document_type == "invoice"]
        purchase_orders: dict[str, list[SupplierDocument]] = defaultdict(list)
        for document in purchase_docs:
            purchase_orders[document.supplier_order_id or str(document.id)].append(document)
        order_count = len(purchase_orders)
        shipping_known = {cost.document_id for cost in supplier_shipping}
        increases = 0
        erosion_products = []
        for mapping in mappings_by_supplier.get(supplier.id, []):
            mapping_costs = costs_by_map.get(mapping.id, [])
            current = _selected_cost(mapping_costs, date_to)
            previous = None
            if current:
                previous = _selected_cost(
                    mapping_costs,
                    current.purchase_date.fromordinal(current.purchase_date.toordinal() - 1),
                )
            if current and previous and current.purchase_date >= date_from and current.net_unit_cost > previous.net_unit_cost:
                increases += 1
                product = catalog_by_id.get(mapping.product_catalog_id)
                net_price = None
                if product and product.price > 0:
                    raw = product.raw or {}
                    net_price = net_product_sale({"prices_include_vat": raw.get("prices_include_vat", False), "vat_rate": raw.get("vat_rate")}, product.price, 1).net_sales
                old_margin = margin_metrics(net_price, 1, previous.net_unit_cost)["margin_percent"] if net_price else None
                new_margin = margin_metrics(net_price, 1, current.net_unit_cost)["margin_percent"] if net_price else None
                erosion_products.append(
                    {
                        "mapping_id": str(mapping.id),
                        "product_name": mapping.product_name,
                        "supplier_sku": mapping.supplier_sku,
                        "previous_cogs": dec_to_float(previous.net_unit_cost),
                        "current_cogs": dec_to_float(current.net_unit_cost),
                        "current_price_net": dec_to_float(net_price) if net_price is not None else None,
                        "margin_change_points": dec_to_float(new_margin - old_margin) if new_margin is not None and old_margin is not None else None,
                        "increase_percent": dec_to_float(
                            (current.net_unit_cost - previous.net_unit_cost) / previous.net_unit_cost * Decimal("100")
                        )
                        if previous.net_unit_cost
                        else None,
                    }
                )
        threshold = supplier.free_shipping_threshold
        threshold_gap = sum(
            (max(threshold - sum((document.net_products_total for document in order_docs), Decimal("0")), Decimal("0")) for order_docs in purchase_orders.values())
            if threshold is not None
            else (),
            Decimal("0"),
        )
        avoidable_freight = sum(
            (
                cost.net_shipping_cost
                for cost in supplier_shipping
                if threshold is not None and cost.order_net_purchase_value >= threshold
            ),
            Decimal("0"),
        )
        rows.append(
            {
                "supplier_id": str(supplier.id),
                "supplier": supplier.name,
                "purchases": dec_to_float(purchases),
                "freight": dec_to_float(freight),
                "freight_ratio": dec_to_float(freight / purchases * Decimal("100")) if purchases else 0,
                "orders": order_count,
                "average_order": dec_to_float(purchases / order_count) if order_count else 0,
                "average_freight_per_order": dec_to_float(freight / order_count) if order_count else 0,
                "free_shipping_orders": sum(1 for order_docs in purchase_orders.values() if all(doc.id in shipping_known for doc in order_docs) and not any(doc.id in paid_shipping_docs for doc in order_docs)),
                "unknown_shipping_orders": sum(1 for order_docs in purchase_orders.values() if not all(doc.id in shipping_known for doc in order_docs) and not any(doc.id in paid_shipping_docs for doc in order_docs)),
                "paid_shipping_orders": sum(1 for order_docs in purchase_orders.values() if any(doc.id in paid_shipping_docs for doc in order_docs)),
                "free_shipping_threshold": dec_to_float(threshold) if threshold is not None else None,
                "threshold_gap": dec_to_float(threshold_gap),
                "potential_freight_savings": dec_to_float(avoidable_freight),
                "price_increases": increases,
                "margin_erosion_products": erosion_products[:10],
                "shipping_trend": [
                    {"month": month, "freight": dec_to_float(sum((cost.net_shipping_cost for cost in supplier_shipping if cost.date.strftime("%Y-%m") == month), Decimal("0")))}
                    for month in sorted({cost.date.strftime("%Y-%m") for cost in supplier_shipping})
                ],
                "shipping_by_type": [
                    {"shipping_type": kind, "freight": dec_to_float(sum((cost.net_shipping_cost for cost in supplier_shipping if cost.shipping_type == kind), Decimal("0")))}
                    for kind in ("INBOUND", "DIRECT_SUPPLIER", "RETURN", "OTHER")
                ],
            }
        )
    return rows


def search_supplier_catalog(db: Session, query: str) -> list[dict[str, Any]]:
    value = query.strip()
    if len(value) < 2:
        return []
    search = "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    products = db.scalars(select(ProductCatalog).where(or_(
        ProductCatalog.name.ilike(search), ProductCatalog.sku.ilike(search),
        ProductCatalog.model.ilike(search), ProductCatalog.product_id.ilike(search), ProductCatalog.ean.ilike(search)
    )).order_by(ProductCatalog.name).limit(30)).all()
    return [{"product_catalog_id": str(product.id), "product_id": product.product_id, "sku": product.sku,
             "model": product.model, "name": product.name, "method": "manual_search", "confidence": 0} for product in products]


def supplier_shipping_simulation(db: Session, supplier_id: UUID, date_from: date, date_to: date, threshold: Decimal) -> dict[str, Any]:
    documents = db.scalars(select(SupplierDocument).where(
        SupplierDocument.supplier_id == supplier_id, SupplierDocument.document_type == "invoice",
        SupplierDocument.document_date.between(date_from, date_to)
    )).all()
    documents = validated_documents(db, documents)
    order_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    order_keys = {}
    for document in documents:
        key = document.supplier_order_id or str(document.id)
        order_keys[document.id] = key
        order_values[key] += document.net_products_total
    freight_by_order: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    if order_keys:
        for freight in db.scalars(select(SupplierShippingCost).where(
            SupplierShippingCost.document_id.in_(list(order_keys)),
            SupplierShippingCost.shipping_type.in_(["INBOUND", "DIRECT_SUPPLIER"])
        )).all():
            freight_by_order[order_keys[freight.document_id]] += freight.net_shipping_cost
    eligible = {key for key, value in order_values.items() if value >= threshold}
    savings = sum((max(freight_by_order[key], Decimal("0")) for key in eligible), Decimal("0"))
    top_up = sum((max(threshold - value, Decimal("0")) for value in order_values.values()), Decimal("0"))
    return {"threshold": dec_to_float(threshold), "eligible_orders": len(eligible), "orders": len(order_values),
            "potential_savings": dec_to_float(savings), "additional_purchase_to_threshold": dec_to_float(top_up)}


def supplier_cost_history(db: Session, mapping_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(select(SupplierProductCost).where(SupplierProductCost.supplier_product_map_id == mapping_id)
                      .order_by(SupplierProductCost.purchase_date.desc(), SupplierProductCost.created_at.desc())).all()
    return [{"id": str(cost.id), "date": cost.purchase_date.isoformat(), "source": cost.source_type,
             "reference": cost.source_reference, "net_unit_cost": dec_to_float(cost.net_unit_cost),
             "quantity": dec_to_float(cost.quantity), "confidence": dec_to_float(cost.source_confidence),
             "currency": cost.currency, "status": cost.status, "product_catalog_id": str(cost.product_catalog_id)} for cost in rows]


def supplier_summary(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    realized = [SupplierDocument.document_date.between(date_from, date_to),
                SupplierDocument.document_type.in_(["invoice", "credit_note"])]
    documents = validated_documents(db, db.scalars(select(SupplierDocument).where(*realized)).all())
    valid_ids = [row.id for row in documents]
    purchases = sum((row.net_products_total for row in documents), Decimal("0"))
    freight = db.scalar(select(func.coalesce(func.sum(SupplierShippingCost.net_shipping_cost), 0))
                        .join(SupplierDocument, SupplierShippingCost.document_id == SupplierDocument.id).where(*realized,
                            SupplierDocument.id.in_(valid_ids)))
    matched = db.scalar(select(func.count()).select_from(SupplierProductMap).where(SupplierProductMap.status == "matched")) or 0
    unmatched = db.scalar(
        select(func.count()).select_from(SupplierProductMap).where(SupplierProductMap.status != "matched")
    ) or 0
    products = supplier_products(db, date_to)
    return {
        "suppliers": db.scalar(select(func.count()).select_from(Supplier)) or 0,
        "purchases": dec_to_float(purchases),
        "freight": dec_to_float(freight),
        "matched_products": int(matched),
        "unmatched_products": int(unmatched),
        "products_with_cogs": sum(1 for row in products if row["current_cogs"] is not None),
    }


def _order_coupon_amount(order: OpenCartOrder) -> Decimal:
    raw = order.raw if isinstance(order.raw, dict) else {}
    for key in ("coupon_value", "coupon_total", "coupon_amount", "discount_value", "discount_total"):
        if raw.get(key) not in (None, ""):
            amount = decimal_value(raw.get(key))
            return amount if amount <= 0 else -amount
    for totals_key in ("totals", "order_totals"):
        totals = raw.get(totals_key)
        if not isinstance(totals, list):
            continue
        amount = Decimal("0")
        for item in totals:
            if not isinstance(item, dict):
                continue
            code = normalize_name(item.get("code"))
            title = normalize_name(item.get("title") or item.get("name"))
            if code != "coupon" and "coupon" not in title and "κουπον" not in title:
                continue
            value = next((item.get(key) for key in ("value", "amount", "total") if item.get(key) not in (None, "")), 0)
            line_amount = decimal_value(value)
            amount += line_amount if line_amount <= 0 else -line_amount
        if amount:
            return amount
    return Decimal("0")


def _catalog_lookup(products: list[ProductCatalog]) -> dict[tuple[str, str], list[ProductCatalog]]:
    lookup: dict[tuple[str, str], list[ProductCatalog]] = defaultdict(list)
    for product in products:
        raw = product.raw if isinstance(product.raw, dict) else {}
        for field, value in (("sku", product.sku), ("model", product.model), ("product_id", product.product_id),
                             ("ean", product.ean or raw.get("ean")), ("ean", product.upc or raw.get("upc"))):
            key = normalize_identifier(value)
            if key and product not in lookup[(field, key)]:
                lookup[(field, key)].append(product)
    return lookup


def _sale_catalog(line: OpenCartOrderProduct, lookup: dict) -> ProductCatalog | None:
    for field, value in (("product_id", line.product_id), ("sku", line.sku), ("model", line.model), ("ean", (line.raw or {}).get("ean"))):
        candidates = lookup.get((field, normalize_identifier(value)), [])
        if candidates:
            return candidates[0] if len(candidates) == 1 else None
    return None


def product_profitability(
    db: Session,
    date_from: date,
    date_to: date,
    sale_statuses: list[str] | None,
) -> list[dict[str, Any]]:
    conditions = [func.date(OpenCartOrder.date_added).between(date_from, date_to)]
    if sale_statuses is not None:
        if not sale_statuses:
            return []
        conditions.append(
            func.lower(func.trim(func.coalesce(OpenCartOrder.order_status, ""))).in_(sale_statuses)
        )
    pairs = db.execute(
        select(OpenCartOrder, OpenCartOrderProduct)
        .join(OpenCartOrderProduct, OpenCartOrderProduct.order_pk == OpenCartOrder.id)
        .where(and_(*conditions))
        .order_by(OpenCartOrder.date_added)
    ).all()
    catalog_products = list(db.scalars(select(ProductCatalog)).all())
    catalog_lookup = _catalog_lookup(catalog_products)
    costs_by_catalog: dict[UUID, list[SupplierProductCost]] = defaultdict(list)
    for cost in validated_cost_rows(db, db.scalars(select(SupplierProductCost).where(SupplierProductCost.purchase_date <= date_to)).all()):
        costs_by_catalog[cost.product_catalog_id].append(cost)

    lines_by_order: dict[UUID, list[tuple[OpenCartOrder, OpenCartOrderProduct]]] = defaultdict(list)
    for order, product in pairs:
        lines_by_order[order.id].append((order, product))

    groups: dict[str, dict[str, Any]] = {}
    for order_lines in lines_by_order.values():
        order = order_lines[0][0]
        bases = [net_product_sale(line.raw or {}, line.price, line.quantity, apply_refunds=False).net_sales or Decimal("0") for _, line in order_lines]
        coupon = _order_coupon_amount(order)
        coupon += abs(decimal_value((order.raw or {}).get("coupon_shipping_share")))
        declared_shares = [present(line.raw or {}, "coupon_share") for _, line in order_lines]
        included = [flag((line.raw or {}).get("includes_order_discount")) for _, line in order_lines]
        mixed_discount_scope = bool(coupon) and any(included) and not all(included) and any(included[i] and declared_shares[i] is None for i in range(len(included)))
        coupon += sum((abs(decimal_value(value)) for value in declared_shares if value is not None), Decimal("0"))
        coupon = min(coupon, Decimal("0"))
        bases = [base if not included[index] and declared_shares[index] is None else Decimal("0") for index, base in enumerate(bases)]
        for (_, line), coupon_share in zip(order_lines, allocate_coupon(bases, coupon)):
            sale = net_product_sale(line.raw or {}, line.price, line.quantity, coupon_share)
            net_sales = sale.net_sales
            if mixed_discount_scope:
                net_sales = None
            if order.currency_code not in (None, "", "EUR"):
                net_sales = None
            if any((order.raw or {}).get(key) for key in ("refund_total", "refunded_amount", "refund_amount")):
                # Order-only refunds cannot safely be attributed to products versus shipping.
                net_sales = None
            catalog = _sale_catalog(line, catalog_lookup)
            sales_key = (line.product_id, line.sku, line.model, line.name, line.brand, line.manufacturer, line.category)
            group_key = json.dumps(sales_key)
            group = groups.setdefault(
                group_key,
                {
                    "product_id": catalog.product_id if catalog else line.product_id,
                    "sku": catalog.sku if catalog else line.sku,
                    "model": catalog.model if catalog else line.model,
                    "name": catalog.name if catalog else line.name,
                    "brand": (catalog.brand or catalog.manufacturer) if catalog else (line.brand or line.manufacturer),
                    "category": catalog.category if catalog else line.category,
                    "quantity": Decimal("0"),
                    "orders": set(),
                    "net_sales": Decimal("0"),
                    "revenue": Decimal("0"),
                    "missing_sales_lines": 0,
                    "known_cogs": Decimal("0"),
                    "known_quantity": Decimal("0"),
                    "missing_cost_lines": 0,
                    "sources": set(),
                    "cost_dates": [],
                    "confidences": [],
                    "cost_provenance": {},
                    "sales_bases": set(),
                    "catalog": catalog,
                    "sales_group_key": list(sales_key),
                },
            )
            quantity = sale.quantity
            group["quantity"] += quantity
            group["orders"].add(order.id)
            group["net_sales"] += net_sales or Decimal("0")
            group["revenue"] += line.price * line.quantity
            group["sales_bases"].add(sale.basis)
            if net_sales is None:
                group["missing_sales_lines"] += 1
            selected = _selected_cost(costs_by_catalog.get(catalog.id, []), order.date_added.date()) if catalog else None
            if selected:
                metrics = margin_metrics(net_sales or 0, quantity, selected.net_unit_cost)
                group["known_cogs"] += metrics["cogs"] or Decimal("0")
                group["known_quantity"] += quantity
                group["sources"].add(selected.source_type)
                group["cost_dates"].append(selected.purchase_date)
                group["confidences"].append(selected.source_confidence)
                group["cost_provenance"][str(selected.id)] = {"source": selected.source_type, "reference": selected.source_reference,
                    "date": selected.purchase_date.isoformat(), "supplier_id": str(selected.supplier_id),
                    "supplier_sku": selected.supplier_sku, "confidence": dec_to_float(selected.source_confidence),
                    "unit_cost": dec_to_float(selected.net_unit_cost)}
            elif quantity:
                group["missing_cost_lines"] += 1

    results = []
    for group in groups.values():
        fully_costed = group["missing_cost_lines"] == 0 and group["missing_sales_lines"] == 0
        metrics = margin_metrics(
            group["net_sales"],
            Decimal("1"),
            group["known_cogs"] if fully_costed else None,
        )
        current_cost = (
            _selected_cost(costs_by_catalog.get(group["catalog"].id, []), date_to)
            if group["catalog"]
            else None
        )
        quantity = group["quantity"]
        results.append(
            {
                "product_id": group["product_id"],
                "sales_group_key": group["sales_group_key"],
                "sku": group["sku"],
                "model": group["model"],
                "name": group["name"],
                "brand": group["brand"] or "Unknown",
                "category": group["category"] or "Unknown",
                "quantity": int(quantity) if quantity == quantity.to_integral_value() else dec_to_float(quantity),
                "orders": len(group["orders"]),
                "average_quantity_per_order": dec_to_float(quantity / len(group["orders"])) if group["orders"] else 0,
                "net_sales": dec_to_float(group["net_sales"]) if not group["missing_sales_lines"] else None,
                "revenue": dec_to_float(group["revenue"]),
                "missing_sales_lines": group["missing_sales_lines"],
                "missing_cost_lines": group["missing_cost_lines"],
                "cogs": dec_to_float(metrics["cogs"]) if metrics["cogs"] is not None else None,
                "gross_profit": dec_to_float(metrics["gross_profit"]) if metrics["gross_profit"] is not None else None,
                "margin_percent": dec_to_float(metrics["margin_percent"]) if metrics["margin_percent"] is not None else None,
                "cost_coverage_percent": dec_to_float(group["known_quantity"] / quantity * Decimal("100")) if quantity else 0,
                "current_unit_cogs": dec_to_float(current_cost.net_unit_cost) if current_cost else None,
                "cogs_source": ", ".join(sorted(group["sources"])) or None,
                "cogs_date": max(group["cost_dates"]).isoformat() if group["cost_dates"] else None,
                "cogs_confidence": dec_to_float(min(group["confidences"])) if group["confidences"] else None,
                "cost_provenance": list(group["cost_provenance"].values()),
                "sales_bases": sorted(group["sales_bases"]),
                "current_cost_date": current_cost.purchase_date.isoformat() if current_cost else None,
            }
        )
    return sorted(results, key=lambda row: row["net_sales"] or 0, reverse=True)
