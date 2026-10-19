from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.connectors.aade_detail import META_KEY, source_fingerprint
from app.models import AADEDocument, SupplierDocument, SupplierProductCost, SupplierProductMap
from app.services.import_service import import_aade_payload
from app.services.supplier_aade_costs import (
    _legacy_source_digest, _source_digest, accept_invoice, aade_invoices,
    invoice_preview, upgrade_source_digest, validated_cost_rows,
)
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_aade_review import pending_costs
from app.services.supplier_aade_rules import review_identity
from app.services.supplier_catalog_pricing import latest_aade_costs
from app.services.supplier_catalog_summary import period_summary
from test_supplier_aade_costs import auto_policy, payload, seed
from test_supplier_aade_partial import mixed_invoice, resolve_second


def provider_detail(fiscal):
    raw = deepcopy(fiscal.raw)
    lines = deepcopy(raw["invoiceDetails"])
    for line in lines:
        if "quantity" in line:
            line["quantity"] = format(Decimal(str(line["quantity"])), ".4f")
    return {**raw, META_KEY: {"status": "verified", "source_hash": source_fingerprint(raw),
                             "invoice": {"invoiceDetails": lines}}}


def numbered_products(db):
    from app.models import ProductCatalog, SupplierCatalogProduct
    actor, supplier, product, item, fiscal = seed(db)
    second = ProductCatalog(sku="SECOND", name="Second product")
    db.add(second)
    db.flush()
    db.add(SupplierCatalogProduct(feed_id=item.feed_id, supplier_code="SECOND", supplier_sku="SECOND",
        name="Second product", product_catalog_id=second.id, is_current=True, last_seen_at=datetime.now(timezone.utc)))
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [fiscal.raw["invoiceDetails"][0],
        {"lineNumber": 2, "itemCode": "SECOND", "itemDescr": "Second product", "quantity": 1,
         "measurementUnit": 1, "netValue": 30, "vatAmount": 7.2}]}
    fiscal.net_value, fiscal.vat_amount, fiscal.gross_value = Decimal(170), Decimal("40.8"), Decimal("210.8")
    db.commit()
    return actor, supplier, product, item, fiscal


def ubl_numbering(fiscal, *, renumber=True):
    raw = provider_detail(fiscal)
    rows = raw[META_KEY]["invoice"]["invoiceDetails"]
    for index, row in enumerate(rows):
        row["_ubl_evidence"] = {"version": 1, "unit_code": "E48", "original_quantity": row["quantity"]}
        if renumber:
            row["lineNumber"] = len(rows) - index
    rows.reverse()
    return raw


@pytest.mark.parametrize("legacy", [False, True])
def test_verified_ubl_numbering_keeps_fiscal_line_identity_and_costs(db, legacy):
    actor, supplier, _, _, fiscal = numbered_products(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    stored = db.scalar(select(SupplierDocument))
    if legacy:
        stored.raw_metadata = {**stored.raw_metadata, "aade_source_digest": _legacy_source_digest(fiscal)}
    before = [(row.id, row.product_catalog_id, row.net_unit_cost) for row in db.scalars(select(SupplierProductCost))]
    original = deepcopy(fiscal.raw)
    fiscal.raw = ubl_numbering(fiscal)
    db.commit()
    for _ in range(3):
        preview = invoice_preview(db, fiscal.id, supplier.id)
        assert not preview["reasons"] and preview["costed_lines"] == 2
        assert all(not row["reasons"] and row["costed"] for row in preview["lines"])
        assert [row["line_number"] for row in preview["lines"]] == ["1", "2"]
        assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == 2
        row = sync_row(fiscal)
        row["raw"] = original
        import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
        db.refresh(fiscal)
    assert [(row.id, row.product_catalog_id, row.net_unit_cost) for row in db.scalars(select(SupplierProductCost))] == before


@pytest.mark.parametrize("field,value", [("quantity", "3"), ("itemCode", "OTHER"), ("measurementUnit", 2),
    ("netValue", 141), ("vatAmount", 34), ("itemDescr", "Another product"), ("recType", 1), ("vatCategory", 2)])
def test_ubl_numbering_recovery_requires_every_other_field_to_match(db, field, value):
    actor, supplier, _, _, fiscal = numbered_products(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    raw = ubl_numbering(fiscal)
    raw[META_KEY]["invoice"]["invoiceDetails"][0][field] = value
    fiscal.raw = raw
    db.flush()
    assert not validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())
    assert any("source changed" in reason for reason in invoice_preview(db, fiscal.id, supplier.id)["reasons"])


@pytest.mark.parametrize("canonical", [False, True])
def test_ubl_audit_only_upgrade_preserves_previously_enriched_cost_sources(db, canonical):
    from app.services.supplier_aade_costs import _canonical_source_digest
    actor, supplier, _, _, fiscal = numbered_products(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    raw = ubl_numbering(fiscal, renumber=False)
    enriched = raw[META_KEY]["invoice"]
    stored = db.scalar(select(SupplierDocument))
    digest = _canonical_source_digest(fiscal, enriched) if canonical else _legacy_source_digest(fiscal, enriched)
    stored.raw_metadata = {**stored.raw_metadata, "aade_source_digest": digest}
    fiscal.raw = raw
    db.flush()
    assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == 2
    assert not invoice_preview(db, fiscal.id, supplier.id)["reasons"]


def test_duplicate_or_unverified_product_codes_cannot_recover_numbered_costs(db):
    actor, supplier, _, _, fiscal = numbered_products(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    raw = ubl_numbering(fiscal)
    rows = raw[META_KEY]["invoice"]["invoiceDetails"]
    rows[0]["itemCode"] = rows[1]["itemCode"]
    fiscal.raw = raw
    db.flush()
    assert not validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())


@pytest.mark.parametrize("partial", [False, True])
def test_previously_enriched_invoice_costs_keep_record_identity_after_numbering_recovery(db, partial):
    from app.models import SupplierDocumentLine
    from app.services.supplier_aade_costs import _canonical_source_digest
    actor, supplier, _, _, fiscal = numbered_products(db)
    original = deepcopy(fiscal.raw)
    # Simulate an old import that used provider line numbering, before recovery.
    provider = ubl_numbering(fiscal)[META_KEY]["invoice"]
    fiscal.raw = provider
    db.commit()
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor,
                   only_line_number="2" if partial else None)
    stored = db.scalar(select(SupplierDocument))
    old_digest = _canonical_source_digest(fiscal, provider)
    stored.raw_metadata = {**stored.raw_metadata, "aade_source_digest": old_digest}
    before = [(row.id, row.product_catalog_id, row.net_unit_cost) for row in db.scalars(select(SupplierProductCost))]
    record_ids = {row.raw_metadata["aade_item_code"]: row.id for row in db.scalars(select(SupplierDocumentLine))}
    fiscal.raw = {**original, META_KEY: {"status": "verified", "source_hash": source_fingerprint(original), "invoice": provider}}
    db.commit()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert not preview["reasons"] and preview["costed_lines"] == len(before)
    assert all(not row["reasons"] for row in preview["lines"])
    assert preview["ready_lines"] == int(partial)
    assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == len(before)
    if partial:
        assert accept_invoice(db, fiscal.id, payload(preview), actor)["costs_created"] == 1
        assert {row.raw_metadata["aade_item_code"]: row.id for row in db.scalars(select(SupplierDocumentLine))} == record_ids
    else:
        assert upgrade_source_digest(db, fiscal.id)
    db.commit()
    row = sync_row(fiscal)
    row["raw"] = original
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert not invoice_preview(db, fiscal.id, supplier.id)["reasons"]
    assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == 2
    after = [(row.id, row.product_catalog_id, row.net_unit_cost) for row in db.scalars(select(SupplierProductCost))]
    assert all(row in after for row in before)


def sync_row(fiscal):
    return {key: getattr(fiscal, key) for key in (
        "source_endpoint", "identity_key", "mark", "uid", "issuer_vat", "counterpart_vat",
        "issue_date", "invoice_type", "document_direction", "series", "aa", "currency",
        "net_value", "vat_amount", "gross_value", "is_cancelled", "cancelled_by_mark", "raw")}


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_provider_quantity_format_keeps_costs_through_repeated_resyncs(db, legacy, partial):
    user, supplier, product, item, fiscal = mixed_invoice(db) if partial else seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    document = db.scalar(select(SupplierDocument))
    if legacy:
        document.raw_metadata = {**document.raw_metadata, "aade_source_digest": _legacy_source_digest(fiscal)}
    original_id = db.scalar(select(SupplierProductCost.id))
    raw = deepcopy(fiscal.raw)
    fiscal.raw = provider_detail(fiscal)
    db.commit()
    for _ in range(3):
        assert not invoice_preview(db, fiscal.id, supplier.id)["reasons"]
        assert latest_aade_costs(db, {product.id}, {supplier.code})[(supplier.code, product.id)][0].net_unit_cost == 70
        assert period_summary(db, fiscal.issue_date, fiscal.issue_date)["rows"][0]["costed_products_net"] == 140
        row = sync_row(fiscal)
        row["raw"] = raw
        import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
        db.refresh(fiscal)
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1
    assert db.scalar(select(SupplierProductCost.id)) == original_id
    if partial:
        resolve_second(db, item)
        result = accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
        assert result["costs_created"] == 1 and result["pending_lines"] == 0
        assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == 2
    else:
        assert accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)["duplicate"]


@pytest.mark.parametrize("quantity", ["2", "2.0000", 2, 2.0])
def test_canonical_cost_source_normalizes_only_quantity_and_amount_scale(db, quantity):
    _, _, _, _, fiscal = seed(db)
    digest = _source_digest(fiscal)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "quantity": quantity}, fiscal.raw["invoiceDetails"][1]]}
    fiscal.net_value = Decimal("145.000000")
    assert _source_digest(fiscal) == digest


@pytest.mark.parametrize("field,value", [
    ("quantity", "2.0001"), ("quantity", True), ("quantity", None),
    ("itemCode", "OTHER"), ("itemDescr", "Different product"),
    ("measurementUnit", 2), ("netValue", 141), ("vatAmount", 34),
    ("vatCategory", 2), ("recType", 1),
])
@pytest.mark.parametrize("legacy", [False, True])
def test_provider_real_line_change_never_reuses_original_cost(db, field, value, legacy):
    user, supplier, _, _, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    document = db.scalar(select(SupplierDocument))
    if legacy:
        document.raw_metadata = {**document.raw_metadata, "aade_source_digest": _legacy_source_digest(fiscal)}
    raw = provider_detail(fiscal)
    raw[META_KEY]["invoice"]["invoiceDetails"][0][field] = value
    fiscal.raw = raw
    db.flush()
    assert not validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())
    assert any("source changed" in reason for reason in invoice_preview(db, fiscal.id, supplier.id)["reasons"])
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1


def test_equivalent_endpoint_copy_and_cancellation_still_checked(db):
    user, supplier, _, _, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    row = sync_row(fiscal)
    row.update(source_endpoint="RequestTransmittedDocs", identity_key="formatted-copy", raw=provider_detail(fiscal))
    copy = AADEDocument(**row)
    db.add(copy)
    db.flush()
    assert not invoice_preview(db, fiscal.id, supplier.id)["reasons"]
    costs = db.scalars(select(SupplierProductCost)).all()
    assert validated_cost_rows(db, costs) == costs
    copy.is_cancelled = True
    db.flush()
    assert not validated_cost_rows(db, costs)


def test_changed_fully_imported_invoice_is_reviewed_and_not_labelled_costed(db):
    user, supplier, _, _, fiscal = seed(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "imported"
    row = sync_row(fiscal)
    row["raw"] = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "quantity": 3}, fiscal.raw["invoiceDetails"][1]]}
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    assert process_aade_costs(db)["status"] == "review"
    listed = aade_invoices(db, supplier.id, fiscal.issue_date, fiscal.issue_date, 0, 10)
    assert listed["rows"][0]["cost_status"] == "review"
    pending = pending_costs(db, fiscal.issue_date, fiscal.issue_date, supplier.id)
    assert pending["total"] == 1 and pending["invoices"][0]["reasons"]
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1
    assert process_aade_costs(db) == {"processed": 0}


def test_manual_complete_cost_is_checked_once_without_endless_review(db):
    user, supplier, _, _, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "imported"
    assert process_aade_costs(db) == {"processed": 0}
    listed = aade_invoices(db, supplier.id, date(2026, 9, 1), date(2026, 9, 1), 0, 10)
    assert listed["rows"][0]["cost_status"] == "imported"


def test_legacy_upgrade_survives_later_aade_quantity_format_change(db):
    user, supplier, _, _, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    document = db.scalar(select(SupplierDocument))
    old = _legacy_source_digest(fiscal)
    document.raw_metadata = {**document.raw_metadata, "aade_source_digest": old}
    fiscal.raw = provider_detail(fiscal)
    db.commit()
    cost_id = db.scalar(select(SupplierProductCost.id))
    assert upgrade_source_digest(db, fiscal.id)
    db.commit()
    assert document.raw_metadata["aade_source_digest_version"] == 2
    assert document.raw_metadata["aade_digest_upgrade"]["previous"] == old
    row = sync_row(fiscal)
    row["raw"] = {key: value for key, value in fiscal.raw.items() if key != META_KEY}
    row["raw"]["invoiceDetails"] = deepcopy(fiscal.raw[META_KEY]["invoice"]["invoiceDetails"])
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    assert validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())
    assert db.scalar(select(SupplierProductCost.id)) == cost_id
    assert not invoice_preview(db, fiscal.id, supplier.id)["reasons"]


def test_worker_upgrades_legacy_complete_evidence_without_reimporting(db, monkeypatch):
    user, supplier, _, _, fiscal = seed(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "imported"
    document = db.scalar(select(SupplierDocument))
    document.raw_metadata = {key: value for key, value in document.raw_metadata.items()
                             if key != "aade_source_digest_version"}
    document.raw_metadata = {**document.raw_metadata, "aade_source_digest": _legacy_source_digest(fiscal)}
    fiscal.raw = provider_detail(fiscal)
    fiscal.raw = {**fiscal.raw, "_catalog_cost": {**fiscal.raw["_catalog_cost"], "next_attempt_at": None}}
    db.commit()
    monkeypatch.setattr("app.services.supplier_aade_jobs.invoice_preview",
                        lambda *args, **kwargs: pytest.fail("Complete evidence must not rescan the XML catalog"))
    assert process_aade_costs(db)["costs_created"] == 0
    assert document.raw_metadata["aade_source_digest_version"] == 2
    assert process_aade_costs(db) == {"processed": 0}
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1


@pytest.mark.parametrize("enriched", [False, True])
def test_legacy_invoice_only_manual_mapping_survives_digest_upgrade(db, enriched):
    from app.services.supplier_aade_review import confirm_line
    from test_supplier_aade_review import request

    user, supplier, product, item, fiscal = seed(db)
    item.product_catalog_id = None
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "itemCode": "MANUAL"}, fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    before = invoice_preview(db, fiscal.id, supplier.id)
    confirm_line(db, fiscal.id, request(before, product, remember_match=False), user)
    mapping = db.scalar(select(SupplierProductMap))
    legacy = _legacy_source_digest(fiscal)
    mapping.identity_key = review_identity("MANUAL", fiscal.mark, "1", legacy, False)
    document = db.scalar(select(SupplierDocument))
    document.raw_metadata = {**document.raw_metadata, "aade_source_digest": legacy}
    if enriched:
        fiscal.raw = provider_detail(fiscal)
    db.commit()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert not preview["reasons"]
    assert preview["lines"][0]["product_catalog_id"] == str(product.id)
    assert not preview["lines"][0]["reasons"]
    assert upgrade_source_digest(db, fiscal.id)
    db.commit()
    row = sync_row(fiscal)
    row["raw"] = {key: value for key, value in fiscal.raw.items() if key != META_KEY}
    row["raw"]["invoiceDetails"] = [
        {**line, "quantity": format(Decimal(str(line["quantity"])), ".4f")} if "quantity" in line else line
        for line in row["raw"]["invoiceDetails"]]
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    refreshed = invoice_preview(db, fiscal.id, supplier.id)
    assert refreshed["lines"][0]["product_catalog_id"] == str(product.id)
    assert not refreshed["lines"][0]["reasons"]
    assert validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())
