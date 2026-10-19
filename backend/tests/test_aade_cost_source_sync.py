from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.connectors.aade_detail import META_KEY, source_fingerprint
from app.models import AADEDocument, SupplierDocument, SupplierProductCost
from app.services.import_service import import_aade_payload
from app.services.supplier_aade_costs import (
    _legacy_source_digest, _source_digest, accept_invoice, aade_invoices,
    invoice_preview, upgrade_source_digest, validated_cost_rows,
)
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_aade_review import pending_costs
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


def test_worker_upgrades_legacy_complete_evidence_without_reimporting(db):
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
    assert process_aade_costs(db)["costs_created"] == 0
    assert document.raw_metadata["aade_source_digest_version"] == 2
    assert process_aade_costs(db) == {"processed": 0}
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1
