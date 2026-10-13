"""Reviewed cost evidence from stored myDATA lines. No AADE network operations."""

import hashlib
import json
import re
from types import SimpleNamespace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import load_only
from sqlalchemy.exc import IntegrityError

from app.models import (AADEDocument, IntegrationSetting, ProductCatalog, Supplier, SupplierCatalogFeed,
                        SupplierCatalogProduct, SupplierDocument, SupplierDocumentLine, SupplierProductCost,
                        SupplierProductMap, SupplierImportBatch)
from app.schemas.suppliers import SupplierAADEAcceptRequest
from app.services.supplier_costing import money, normalize_identifier, supplier_mapping_identity
from app.services.supplier_identity import normalize_vat, fiscal_supplier_vat
from app.connectors.aade_detail import effective_invoice, detail_info


_ANTHEMIDIS_CATALOG_CODE = r"(?:[0-9]{5,6}-[0-9]{1,3}|[0-9]{6})"


def anthemidis_title_codes(description):
    """Standalone numeric catalog codes, including variants such as 11703-6."""
    return set(re.findall(rf"(?<![\w.,/+\-]){_ANTHEMIDIS_CATALOG_CODE}(?![\w.,/+\-])", description))


def pick(row, *keys):
    if not isinstance(row, dict):
        return None
    lowered = {str(key).lower(): value for key, value in row.items()}
    return next((lowered[key.lower()] for key in keys if key.lower() in lowered), None)


def numeric(value):
    if value in (None, "") or isinstance(value, (dict, list, bool)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and abs(result) < Decimal("1000000000") else None
    except InvalidOperation:
        return None


def line_rows(raw):
    raw = effective_invoice(raw)
    rows = pick(raw, "invoiceDetails", "invoice_details", "invoiceRows", "invoice_rows", "lineItems", "line_items", "lines")
    if isinstance(rows, dict):
        rows = pick(rows, "invoiceDetails", "invoiceDetail", "invoiceRow", "row", "line") or rows
    if rows is None:
        return []
    return rows if isinstance(rows, list) else [rows]


def parse_lines(raw, *, confirm_missing_units=False):
    result = []
    for index, row in enumerate(line_rows(raw), 1):
        description = str(pick(row, "itemDescr", "itemDescription", "productDescription", "description", "lineComments", "comments", "name", "title") or "")[:1000]
        code = str(pick(row, "itemCode", "item_code", "productCode", "product_code", "code") or "").strip()
        qty = numeric(pick(row, "quantity", "qty"))
        net = numeric(pick(row, "netValue", "totalNetValue", "net"))
        vat = numeric(pick(row, "vatAmount", "totalVatAmount", "vat"))
        unit = str(pick(row, "measurementUnit", "unit", "unitCode") or "").strip()
        shipping = not code and any(token in description.lower() for token in ("shipping", "courier", "μεταφορ", "αποστολ"))
        # MEGAPAP uses an explicit fiscal freight code, not a catalog product.
        shipping = shipping or (code.upper() == "ΜΤΦ" and description.lower().startswith("μεταφορικά"))
        source_unit = unit
        unit_confirmed = bool(not shipping and not unit and confirm_missing_units)
        if unit_confirmed:
            unit = "piece"
        reasons = []
        record_type = str(pick(row, "recType") or "")
        if record_type:
            reasons.append("Special fiscal line (fee / tax / adjustment) requires separate review.")
        if net is None or net < 0 or vat is None or vat < 0:
            reasons.append("Missing or invalid net value / VAT; negative adjustments require review.")
        if not shipping and (qty is None or qty <= 0):
            reasons.append("Missing or invalid product quantity.")
        if not shipping and unit not in {"1", "pcs", "PCS", "piece", "pieces", "τεμ", "ΤΕΜ"}:
            reasons.append("Purchase unit is not explicitly pieces; pack conversion requires review.")
        if not shipping and not code:
            reasons.append("Missing item code; description alone is not an automatic match.")
        result.append({"line_number": str(pick(row, "lineNumber", "lineNo") or index), "item_code": code,
                       "description": description, "line_type": "shipping" if shipping else "product",
                       "quantity": qty, "unit": unit, "source_unit": source_unit,
                       "unit_confirmed": unit_confirmed, "net_value": net, "vat_amount": vat,
                       "vat_category": pick(row, "vatCategory"),
                       "unit_cost_net": money(net / qty) if not shipping and not reasons and net is not None and qty and qty > 0 else None,
                       "reasons": reasons})
    return result


def own_vat(db):
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "aade"))
    return normalize_vat((integration.config or {}).get("vat_number")) if integration else ""


def _invoice_key(document):
    return f"aade:{normalize_vat(document.issuer_vat)}:{document.mark}"


def _source_digest(document):
    return hashlib.sha256(json.dumps({"issuer": document.issuer_vat, "recipient": document.counterpart_vat,
        "date": str(document.issue_date), "mark": document.mark, "type": document.invoice_type,
        "series": document.series, "number": document.aa, "currency": document.currency,
        "net": str(document.net_value), "vat": str(document.vat_amount), "gross": str(document.gross_value),
        "lines": line_rows(document.raw or {})}, sort_keys=True, default=str).encode()).hexdigest()


def aade_invoices(db, supplier_id, start, end, offset, limit):
    supplier = db.get(Supplier, supplier_id)
    if not supplier or not supplier.vat_number:
        raise ValueError("Save the supplier's AFM in Settings first.")
    vat = normalize_vat(supplier.vat_number)
    issuer_country = func.upper(func.trim(case((AADEDocument.raw["record_type"].astext == "book_info",
                         func.coalesce(AADEDocument.raw["counterpart"]["country"].astext,
                                       AADEDocument.raw["invoiceHeader"]["counterpart"]["country"].astext)),
                        else_=func.coalesce(AADEDocument.raw["issuer"]["country"].astext,
                                            AADEDocument.raw["invoiceHeader"]["issuer"]["country"].astext))))
    vat_filter = AADEDocument.issuer_vat.in_([vat, "EL" + vat])
    if vat[:2].isalpha():
        country = vat[:2]
        vat_filter = or_(vat_filter, (AADEDocument.issuer_vat == vat[2:]) & (issuer_country == country))
    else:
        vat_filter = vat_filter & or_(issuer_country.is_(None), issuer_country.in_(["", "GR", "EL"]))
    filters = [AADEDocument.document_direction == "expense", vat_filter,
               AADEDocument.issue_date.between(start, end)]
    count = db.scalar(select(func.count()).select_from(AADEDocument).where(*filters))
    documents = db.scalars(select(AADEDocument).where(*filters).order_by(AADEDocument.issue_date.desc(), AADEDocument.id)
                           .offset(offset).limit(limit)).all()
    return {"total": count, "rows": [{"id": str(row.id), "date": row.issue_date, "mark": row.mark,
        "invoice_type": row.invoice_type, "number": f"{row.series or ''} / {row.aa or ''}",
        "net_value": row.net_value, "gross_value": row.gross_value,
        "cancelled": row.is_cancelled or bool(row.cancelled_by_mark),
        "cost_status": (row.raw or {}).get("_catalog_cost", {}).get("status"),
        "pending_lines": (row.raw or {}).get("_catalog_cost", {}).get("pending_lines"),
        "record_type": (row.raw or {}).get("record_type", "full_document")} for row in documents]}


def invoice_preview(db, document_id, supplier_id, *, lock=False, confirm_missing_units=False, matching_cache=None):
    document = db.get(AADEDocument, document_id, with_for_update=lock, populate_existing=lock)
    supplier = db.get(Supplier, supplier_id)
    if document is None or supplier is None:
        raise ValueError("AADE invoice or supplier not found.")
    reasons = []
    vat = normalize_vat(supplier.vat_number)
    same_vat = [row for row in db.scalars(select(Supplier)).all() if vat and normalize_vat(row.vat_number) == vat]
    if not vat or fiscal_supplier_vat(document.issuer_vat, document.raw or {}) != vat or len(same_vat) != 1:
        reasons.append("Issuer AFM does not identify exactly one registered supplier.")
    recipient = own_vat(db)
    if not recipient or normalize_vat(document.counterpart_vat) != recipient:
        reasons.append("Invoice recipient does not match the configured INDE AFM.")
    if (document.raw or {}).get("record_type", "full_document") != "full_document":
        reasons.append("Book / VAT summaries are not product invoices.")
    if document.document_direction != "expense" or document.invoice_type not in {"1.1", "1.2", "1.3"}:
        reasons.append("Only purchase invoices for goods qualify; credits, delivery notes and services require separate review.")
    if document.currency != "EUR" or document.issue_date > date.today() or not document.mark or not document.aa:
        reasons.append("Missing MARK / invoice number, unsupported currency or future invoice.")
    copies = db.scalars(select(AADEDocument).where(AADEDocument.mark == document.mark)).all() if document.mark else [document]
    if any(row.is_cancelled or row.cancelled_by_mark for row in copies):
        reasons.append("Invoice is cancelled.")
    full_copies = [row for row in copies if (row.raw or {}).get("record_type", "full_document") == "full_document"]
    if any(_source_digest(row) != _source_digest(document) for row in full_copies):
        reasons.append("Conflicting copies of the same MARK require review.")
    lines = parse_lines(document.raw or {}, confirm_missing_units=confirm_missing_units)
    if not lines or len(lines) > 1000:
        reasons.append("Invoice has no usable product detail or exceeds the review limit.")
        lines = lines[:1000]
    if len({line["line_number"] for line in lines}) != len(lines):
        reasons.append("Duplicate line numbers.")
    if lines and all(line["net_value"] is not None and line["vat_amount"] is not None for line in lines):
        net = sum((line["net_value"] for line in lines), Decimal("0"))
        tax = sum((line["vat_amount"] for line in lines), Decimal("0"))
        if abs(net - document.net_value) > Decimal("0.02") or abs(tax - document.vat_amount) > Decimal("0.02") or abs(net + tax - document.gross_value) > Decimal("0.02"):
            reasons.append("Invoice totals do not reconcile to the stored lines; fees / discounts require review.")
    else:
        reasons.append("Invoice amounts cannot be reconciled; missing line amounts require review.")
    if any((line["net_value"] is not None and line["net_value"] < 0) or
           (line["vat_amount"] is not None and line["vat_amount"] < 0) for line in lines):
        reasons.append("Negative invoice adjustments require review before costing.")
    # Matching needs identifiers only, not thousands of descriptions/raw XML rows.
    catalog_query = select(SupplierCatalogProduct, ProductCatalog).options(
        load_only(SupplierCatalogProduct.id, SupplierCatalogProduct.supplier_code,
                  SupplierCatalogProduct.supplier_sku, SupplierCatalogProduct.ean),
        load_only(ProductCatalog.id, ProductCatalog.sku, ProductCatalog.model, ProductCatalog.ean,
                  ProductCatalog.upc, ProductCatalog.mpn)
    ).join(SupplierCatalogFeed,
        SupplierCatalogFeed.id == SupplierCatalogProduct.feed_id).outerjoin(ProductCatalog,
        ProductCatalog.id == SupplierCatalogProduct.product_catalog_id).where(SupplierCatalogFeed.code == supplier.code,
        SupplierCatalogProduct.is_current.is_(True))
    if lock:
        catalog_query = catalog_query.with_for_update(of=SupplierCatalogProduct)
    cached = matching_cache.get(supplier.id) if matching_cache is not None and not lock else None
    catalogs = cached[0] if cached else db.execute(catalog_query).all()
    if lock:
        product_ids = {product.id for _, product in catalogs if product is not None}
        db.scalars(select(ProductCatalog.id).where(ProductCatalog.id.in_(product_ids)).with_for_update()).all()
    index = {}
    title_index = {}
    title_matching = vat == "084146750"
    for item, product in catalogs:
        for identifier in (item.supplier_code, item.supplier_sku, item.ean):
            if identifier:
                index.setdefault(normalize_identifier(identifier), {})[item.id] = (item, product)
        if title_matching:
            for identifier in (item.supplier_code, item.supplier_sku):
                if identifier and re.fullmatch(_ANTHEMIDIS_CATALOG_CODE, identifier):
                    title_index.setdefault(identifier, {})[item.id] = (item, product)
    mappings = cached[1] if cached else db.scalars(select(SupplierProductMap).where(SupplierProductMap.supplier_id == supplier.id)).all()
    if matching_cache is not None and not lock:
        matching_cache[supplier.id] = (catalogs, mappings)
    from app.services.supplier_aade_rules import reviewed_mapping, mapping_valid, xml_identity
    digest = _source_digest(document)
    for line in lines:
        line.update(product_catalog_id=None, inde_sku=None, supplier_sku=None, supplier_code=None, supplier_ean=None,
                    match_method=None, matched_item_code=None, mapping_id=None, xml_candidates=[])
        if line["line_type"] == "shipping":
            continue
        candidates = dict(index.get(normalize_identifier(line["item_code"]), {})) if line["item_code"] else {}
        method, matched_code = "invoice_code", line["item_code"]
        if title_matching:
            title_codes = anthemidis_title_codes(line["description"])
            if len(title_codes) > 1:
                line["reasons"].append("Multiple Anthemidis catalog codes in the invoice title require review.")
            elif title_codes:
                title_code = next(iter(title_codes))
                title_matches = title_index.get(title_code, {})
                if title_matches:
                    if not candidates:
                        method, matched_code = "anthemidis_title_code", title_code
                    candidates.update(title_matches)
        matches = sorted(candidates.values(), key=lambda row: str(row[0].id))
        line["xml_candidates"] = [{"id": str(item.id), **xml_identity(item)} for item, _ in matches]
        manual = reviewed_mapping(mappings, line, document, digest)
        if manual:
            product = db.get(ProductCatalog, manual.product_catalog_id, options=[load_only(
                ProductCatalog.id, ProductCatalog.sku, ProductCatalog.model, ProductCatalog.ean,
                ProductCatalog.upc, ProductCatalog.mpn)]) if manual.product_catalog_id else None
            review = (manual.raw_metadata or {}).get("aade_review", {})
            saved_xml = review.get("xml_identity")
            current_xml = next((item for item, _ in catalogs if str(item.id) == review.get("catalog_item_id")), None)
            if not mapping_valid(manual, product) or (saved_xml and current_xml and xml_identity(current_xml) != saved_xml):
                line["reasons"].append("Reviewed product identifiers changed; confirm the mapping again.")
            else:
                line["reasons"] = [reason for reason in line["reasons"] if reason not in {
                    "Missing item code; description alone is not an automatic match.",
                    "Multiple Anthemidis catalog codes in the invoice title require review."}]
                if not line["source_unit"] and review.get("missing_unit_is_piece"):
                    line["unit"], line["unit_confirmed"] = "piece", True
                    line["reasons"] = [reason for reason in line["reasons"] if reason !=
                        "Purchase unit is not explicitly pieces; pack conversion requires review."]
                line.update(product_catalog_id=str(product.id), inde_sku=product.sku,
                    supplier_sku=manual.supplier_sku, supplier_code=manual.supplier_code, supplier_ean=manual.supplier_ean,
                    match_method="aade_manual_reviewed", matched_item_code=line["item_code"], mapping_id=str(manual.id))
                if not line["reasons"]:
                    line["unit_cost_net"] = money(line["net_value"] / line["quantity"])
            continue
        if len(matches) == 1 and matches[0][1] is not None:
            item, product = matches[0]
            line.update(product_catalog_id=str(product.id), inde_sku=product.sku,
                        supplier_sku=item.supplier_sku, supplier_code=item.supplier_code, supplier_ean=item.ean,
                        match_method=method, matched_item_code=matched_code)
            identity = supplier_mapping_identity(item.supplier_sku, item.ean, item.supplier_code, line["description"])
            prior = next((row for row in mappings if row.identity_key == identity), None)
            if prior and (prior.product_catalog_id not in (None, product.id) or prior.conversion_factor != 1 or prior.pack_quantity != 1):
                line["reasons"].append("Existing mapping / pack conversion conflicts with this XML product.")
        else:
            line["reasons"].append("Ambiguous supplier XML code." if len(matches) > 1 else
                "XML product is not linked to an INDE product." if matches else
                "No unique INDE product through this supplier XML.")
        if line["reasons"]:
            line["unit_cost_net"] = None
    if not any(line["line_type"] == "product" for line in lines):
        reasons.append("No product lines.")
    existing = db.scalar(select(SupplierDocument).where(SupplierDocument.identity_key == _invoice_key(document)))
    legacy_numbers = {document.aa, f"{document.series or ''}/{document.aa or ''}",
                      f"{document.series or ''} / {document.aa or ''}"}
    legacy_match = (SupplierDocument.aade_document_id.in_([row.id for row in copies]) |
                    SupplierDocument.document_number.in_(legacy_numbers))
    legacy = db.scalar(select(SupplierDocument.id).where(SupplierDocument.supplier_id == supplier.id,
        SupplierDocument.document_date == document.issue_date, SupplierDocument.document_type == "invoice",
        SupplierDocument.identity_key != _invoice_key(document), legacy_match).limit(1))
    if legacy:
        reasons.append("This fiscal invoice already exists from another import; reconciliation required to avoid double counting.")
    costed = {}
    if existing:
        if (existing.raw_metadata or {}).get("aade_source_digest") != _source_digest(document):
            reasons.append("Imported fiscal source changed; reconciliation required before adding costs.")
        costed = dict(db.execute(select(SupplierDocumentLine.line_number, SupplierProductCost.product_catalog_id)
            .join(SupplierProductCost, SupplierProductCost.source_line_id == SupplierDocumentLine.id)
            .where(SupplierDocumentLine.document_id == existing.id)).all())
    for line in lines:
        line["costed"] = line["line_number"] in costed
        if line["costed"] and str(costed[line["line_number"]]) != line["product_catalog_id"]:
            line["reasons"].append("Previously costed product mapping changed; existing evidence retained for review.")
        line["ready"] = line["line_type"] == "product" and not line["reasons"] and not line["costed"]
    fingerprint = hashlib.sha256(json.dumps({"source": _source_digest(document), "supplier": str(supplier.id),
        "vat": vat, "recipient": recipient, "lines": lines, "reasons": reasons,
        "confirm_missing_units": confirm_missing_units}, sort_keys=True, default=str).encode()).hexdigest()
    return {"id": str(document.id), "supplier_id": str(supplier.id), "supplier": supplier.name,
            "issuer_vat": document.issuer_vat, "date": document.issue_date, "mark": document.mark,
            "number": f"{document.series or ''}/{document.aa or ''}", "net_value": document.net_value,
            "vat_amount": document.vat_amount, "gross_value": document.gross_value, "lines": lines,
            "provider_detail": detail_info(document.raw or {}),
            "confirm_missing_units": confirm_missing_units,
            "needs_unit_confirmation": any(line["line_type"] == "product" and not line["source_unit"] for line in lines),
            "reasons": reasons, "fingerprint": fingerprint, "source_digest": digest, "imported": bool(existing),
            "ready_lines": sum(line["ready"] for line in lines),
            "pending_lines": sum(line["line_type"] == "product" and not line["costed"] and not line["ready"] for line in lines),
            "costed_lines": len(costed),
            "can_import": not reasons and any(line["ready"] for line in lines)}


def accept_invoice(db, document_id, payload, user, *, automated=False, only_line_number=None):
    from app.services.supplier_service import _create_cost_from_line, _create_shipping_cost

    if not payload.confirm_products_and_units:
        raise ValueError("Confirm the product matches and one purchase piece per INDE sales unit.")
    db.execute(text("SELECT pg_advisory_xact_lock(841650721)"))
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise ValueError("Supplier not found.")
    lock_key = int.from_bytes(hashlib.sha256(supplier.code.encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    preview = invoice_preview(db, document_id, supplier.id, lock=True,
                              confirm_missing_units=payload.confirm_missing_units)
    if preview["imported"] and not preview["can_import"] and not preview["reasons"]:
        return {"duplicate": True, "costs_created": 0, "pending_lines": preview["pending_lines"]}
    if preview["fingerprint"] != payload.fingerprint or not preview["can_import"]:
        raise ValueError("Invoice / mapping changed or needs review. Reload the preview before importing.")
    # The explicit review authorizes the XML bridge, not the older generic
    # importer heuristics (MEGAPAP models and own SKUs can be different).
    mappings = {}
    for line in preview["lines"]:
        if not line["ready"] or (only_line_number is not None and line["line_number"] != only_line_number):
            continue
        identity = supplier_mapping_identity(line["supplier_sku"], line["supplier_ean"], line["supplier_code"], line["description"])
        mapping = db.get(SupplierProductMap, line["mapping_id"], with_for_update=True) if line["mapping_id"] else db.scalar(
            select(SupplierProductMap).where(SupplierProductMap.supplier_id == supplier.id,
                SupplierProductMap.identity_key == identity).with_for_update())
        if mapping is None:
            mapping = SupplierProductMap(supplier_id=supplier.id, identity_key=identity,
                supplier_code=line["supplier_code"], supplier_sku=line["supplier_sku"], supplier_ean=line["supplier_ean"],
                pack_quantity=1, conversion_factor=1, purchase_unit=line["unit"], sales_unit="piece")
            db.add(mapping)
        product = db.get(ProductCatalog, line["product_catalog_id"])
        mapping.product_catalog_id, mapping.opencart_sku, mapping.opencart_model = product.id, product.sku, product.model
        mapping.opencart_product_id, mapping.product_name = product.product_id, product.name
        if not line["mapping_id"]:
            mapping.verified, mapping.verified_by, mapping.verified_at = True, user.id, datetime.now(timezone.utc)
            mapping.status, mapping.confidence, mapping.match_method = "matched", Decimal("1"), "aade_xml_reviewed"
        audit = list((mapping.raw_metadata or {}).get("verification_audit", []))
        audit.append({"user_id":str(user.id), "automated": automated, "at":datetime.now(timezone.utc).isoformat(), "aade_mark":preview["mark"],
                      "product":str(product.id), "factor":"1", "method":mapping.match_method})
        mapping.raw_metadata = {**(mapping.raw_metadata or {}), "verification_audit":audit}
        db.flush()
        mappings[line["line_number"]] = mapping
    source = db.get(AADEDocument, document_id)
    document = db.scalar(select(SupplierDocument).where(SupplierDocument.identity_key == _invoice_key(source)).with_for_update())
    if document is None:
        batch = SupplierImportBatch(supplier_id=supplier.id, source_type="xml",
            source_reference=f"AADE MARK {source.mark}", content_hash=_source_digest(source),
            status="completed", imported_documents=1)
        db.add(batch)
        db.flush()
        document = SupplierDocument(supplier_id=supplier.id, import_batch_id=batch.id,
            identity_key=_invoice_key(source), aade_document_id=source.id, document_type="invoice",
            document_number=preview["number"], document_date=preview["date"], currency="EUR",
            net_products_total=sum(line["net_value"] for line in preview["lines"] if line["line_type"] == "product"),
            net_shipping_total=sum(line["net_value"] for line in preview["lines"] if line["line_type"] == "shipping"),
            net_other_total=0, vat_total=preview["vat_amount"], gross_total=preview["gross_value"], raw_metadata={})
        db.add(document)
        db.flush()
    # Keep the full reconciled invoice, including unresolved product lines.
    # Only ready lines receive a verified mapping and a product cost record.
    stored = {line.line_number: line for line in db.scalars(select(SupplierDocumentLine)
        .where(SupplierDocumentLine.document_id == document.id)).all()}
    created = 0
    for line in preview["lines"]:
        if line["costed"]:
            continue
        record = stored.get(line["line_number"])
        if record is None:
            record = SupplierDocumentLine(document_id=document.id, line_number=line["line_number"])
            db.add(record)
        record.line_type, record.description = line["line_type"], line["description"]
        record.supplier_code, record.supplier_sku, record.supplier_ean = line["supplier_code"], line["supplier_sku"], line["supplier_ean"]
        record.quantity, record.unit = line["quantity"] or 0, line["unit"]
        record.net_line_total, record.vat_amount = line["net_value"], line["vat_amount"]
        record.net_unit_cost = line["unit_cost_net"] or 0
        record.unit_price_before_discount = record.net_unit_cost
        record.gross_total = line["net_value"] + line["vat_amount"]
        record.raw_metadata = {"aade_item_code": line["item_code"], "aade_vat_category": line["vat_category"],
            "aade_match_method": line["match_method"], "aade_matched_item_code": line["matched_item_code"],
            "aade_source_unit": line["source_unit"], "aade_unit_confirmed": line["unit_confirmed"],
            "aade_pending_reasons": line["reasons"], "vat_rate_not_supplied": True}
        mapping = mappings.get(line["line_number"])
        record.supplier_product_map_id = mapping.id if mapping else None
        db.flush()
        if mapping:
            cost = _create_cost_from_line(db, supplier=supplier, document=document, line=record, mapping=mapping)
            if cost is None or str(cost.product_catalog_id) != line["product_catalog_id"]:
                raise ValueError("Catalog match changed while importing; no costs saved.")
            cost.source_type, cost.source_confidence = "aade_invoice", Decimal("1")
            cost.source_reference = f"AADE MARK {source.mark}"
            created += 1
        elif line["line_type"] == "shipping" and not line["reasons"]:
            _create_shipping_cost(db, supplier=supplier, document=document, line=record,
                                  source_payload=SimpleNamespace(shipping_type="INBOUND", cbm=None, weight=None, notes=None))
    pending = sum(line["line_type"] == "product" and not line["costed"] and line["line_number"] not in mappings
                  for line in preview["lines"])
    document.raw_metadata = {**document.raw_metadata, "aade_source_digest": _source_digest(source),
                             "aade_reviewed_by": str(user.id), "aade_fingerprint": preview["fingerprint"],
                             "aade_confirm_missing_units": payload.confirm_missing_units,
                             "aade_automated": automated, "aade_partial": bool(pending),
                             "aade_pending_lines": pending}
    db.commit()
    return {"duplicate": False, "costs_created": created, "mark": source.mark,
            "pending_lines": pending}


def import_cost_batch(db, payload, user):
    """Bounded, user-authorized imports; one blocked invoice cannot stop the batch."""
    if not payload.confirm_products_and_units:
        raise ValueError("Confirm one purchase unit equals one INDE sales unit before importing costs.")
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None or not supplier.vat_number:
        raise ValueError("Save the supplier's AFM first.")
    vat = normalize_vat(supplier.vat_number)
    filters = [AADEDocument.document_direction == "expense",
               AADEDocument.issuer_vat.in_([vat, "EL" + vat]),
               AADEDocument.issue_date.between(payload.date_from, payload.date_to),
               func.coalesce(AADEDocument.raw["record_type"].astext, "full_document") == "full_document"]
    total = db.scalar(select(func.count()).select_from(AADEDocument).where(*filters))
    ids = db.scalars(select(AADEDocument.id).where(*filters)
                     .order_by(AADEDocument.issue_date.desc(), AADEDocument.id)
                     .offset(payload.offset).limit(1)).all()
    rows = []
    for document_id in ids:
        try:
            preview = invoice_preview(db, document_id, payload.supplier_id,
                                      confirm_missing_units=payload.confirm_missing_units)
            result = {"id": str(document_id), "number": preview["number"], "mark": preview["mark"],
                      "costs_created": 0, "status": "review", "reasons": []}
            if preview["can_import"]:
                accepted = accept_invoice(db, document_id, SupplierAADEAcceptRequest(
                    supplier_id=payload.supplier_id, fingerprint=preview["fingerprint"],
                    confirm_products_and_units=True, confirm_missing_units=payload.confirm_missing_units), user)
                result.update(status="partial" if accepted.get("pending_lines") else "imported",
                              costs_created=accepted["costs_created"])
                result["reasons"] = list(dict.fromkeys(reason for line in preview["lines"] for reason in line["reasons"]))
            elif preview["imported"] and not preview["pending_lines"] and not preview["reasons"]:
                result["status"] = "already_imported"
            else:
                result["reasons"] = preview["reasons"] + list(dict.fromkeys(
                    reason for line in preview["lines"] for reason in line["reasons"]))
            rows.append(result)
        except ValueError as exc:
            rows.append({"id": str(document_id), "number": "", "mark": "", "status": "review",
                         "costs_created": 0, "reasons": [str(exc)]})
        except IntegrityError:
            rows.append({"id": str(document_id), "number": "", "mark": "", "status": "review",
                         "costs_created": 0, "reasons": ["Invoice conflicts with existing cost evidence; review required."]})
        finally:
            db.rollback()
    next_offset = payload.offset + len(ids)
    return {"rows": rows, "total": total, "next_offset": next_offset if ids and next_offset < total else None,
            "costs_created": sum(row["costs_created"] for row in rows)}


def validated_documents(db, documents):
    """Fiscal provenance remains valid only while the stored source is unchanged."""
    sourced = [row for row in documents if (row.raw_metadata or {}).get("aade_source_digest")]
    if not sourced:
        return documents
    evidence = db.execute(select(SupplierDocument, AADEDocument, Supplier)
        .join(AADEDocument, AADEDocument.id == SupplierDocument.aade_document_id)
        .join(Supplier, Supplier.id == SupplierDocument.supplier_id)
        .where(SupplierDocument.id.in_([row.id for row in sourced]))).all()
    marks = [fiscal.mark for _, fiscal, _ in evidence]
    copies = db.scalars(select(AADEDocument).where(AADEDocument.mark.in_(marks))).all()
    invalid_marks = {row.mark for row in copies if row.is_cancelled or row.cancelled_by_mark}
    digests = {}
    for row in copies:
        if (row.raw or {}).get("record_type", "full_document") == "full_document":
            digests.setdefault(row.mark, set()).add(_source_digest(row))
    recipient = own_vat(db)
    valid_ids = {document.id for document, fiscal, supplier in evidence
        if fiscal.mark not in invalid_marks and len(digests.get(fiscal.mark, set())) == 1
        and fiscal.document_direction == "expense" and fiscal.currency == "EUR"
        and fiscal.invoice_type in {"1.1", "1.2", "1.3"}
        and normalize_vat(fiscal.issuer_vat) == normalize_vat(supplier.vat_number)
        and recipient and normalize_vat(fiscal.counterpart_vat) == recipient
        and document.raw_metadata.get("aade_source_digest") == _source_digest(fiscal)}
    return [row for row in documents if not (row.raw_metadata or {}).get("aade_source_digest") or row.id in valid_ids]


def validated_cost_rows(db, costs):
    """Never keep using an accepted invoice after fiscal cancellation/correction."""
    sourced = [row for row in costs if row.source_type == "aade_invoice"]
    if not sourced:
        return costs
    evidence = db.execute(select(SupplierDocumentLine.id, SupplierDocument, AADEDocument, Supplier)
        .join(SupplierDocument, SupplierDocument.id == SupplierDocumentLine.document_id)
        .join(AADEDocument, AADEDocument.id == SupplierDocument.aade_document_id)
        .join(Supplier, Supplier.id == SupplierDocument.supplier_id)
        .where(SupplierDocumentLine.id.in_([row.source_line_id for row in sourced]))).all()
    valid_ids = {row.id for row in validated_documents(db, [doc for _, doc, _, _ in evidence])
                 if (row.raw_metadata or {}).get("aade_source_digest")}
    valid_lines = {line_id for line_id, document, _, _ in evidence if document.id in valid_ids}
    return [row for row in costs if row.source_type != "aade_invoice" or row.source_line_id in valid_lines]
