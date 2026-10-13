from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (ProductCatalog, SupplierCatalogFeed, SupplierDocument, SupplierDocumentLine,
                        SupplierProductCost, SupplierProductMap)
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, validated_cost_rows
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_aade_rules import product_identity, review_identity
from app.services.supplier_catalog_service import apply_catalog
from test_supplier_aade_costs import seed, payload, auto_policy
from test_supplier_catalog_analysis import catalog


def pakketo(db):
    actor, supplier, own, item, fiscal = seed(db)
    supplier.code, supplier.vat_number = "PAKKETO", "800749270"
    feed = db.get(SupplierCatalogFeed, item.feed_id)
    feed.code, feed.adapter = supplier.code, "pakoworld"
    feed.counts = {"products": 1, "matched": 0, "ambiguous": 1, "unmatched": 0}
    own.sku, own.ean = "499-000039", "5207351271386"
    item.supplier_code, item.supplier_sku, item.ean = own.sku, None, own.ean
    item.product_catalog_id, item.match_method = None, "ambiguous"
    item.details = {"sell_step": "1"}
    fiscal.issuer_vat = supplier.vat_number
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "itemCode": own.sku}, fiscal.raw["invoiceDetails"][1]]}
    db.add(ProductCatalog(sku="029-000326", name="Old chair", ean=own.ean))
    db.commit()
    return actor, supplier, own, item, fiscal


@pytest.mark.parametrize("xml_state", ["ambiguous", "wrong_product", "missing", "no_feed"])
def test_direct_invoice_sku_is_independent_of_xml_and_shared_ean(db, xml_state):
    actor, supplier, own, item, fiscal = pakketo(db)
    if xml_state == "wrong_product":
        item.product_catalog_id = db.scalar(select(ProductCatalog.id).where(ProductCatalog.sku == "029-000326"))
    elif xml_state in {"missing", "no_feed"}:
        feed = db.get(SupplierCatalogFeed, item.feed_id)
        db.delete(item)
        db.flush()
        if xml_state == "no_feed":
            db.delete(feed)
    db.commit()
    before = invoice_preview(db, fiscal.id, supplier.id)
    line = before["lines"][0]
    assert before["can_import"] and line["product_catalog_id"] == str(own.id)
    assert line["match_method"] == "aade_pakketo_sku" and line["xml_candidates"] == []
    result = accept_invoice(db, fiscal.id, payload(before), actor)
    assert result["costs_created"] == 1 and result["pending_lines"] == 0
    cost = db.scalar(select(SupplierProductCost))
    assert cost.product_catalog_id == own.id and cost.net_unit_cost == 70
    assert cost.source_type == "aade_invoice" and cost.source_confidence == 1
    assert validated_cost_rows(db, [cost]) == [cost]
    mapping = db.get(SupplierProductMap, cost.supplier_product_map_id)
    assert mapping.match_method == "aade_pakketo_sku" and mapping.conversion_factor == mapping.pack_quantity == 1
    assert mapping.supplier_sku == own.sku and mapping.supplier_ean is None
    assert cost.raw_metadata["aade_match_method"] == "aade_pakketo_sku"
    assert own.price == 124
    assert accept_invoice(db, fiscal.id, payload(before), actor)["duplicate"]
    if xml_state in {"ambiguous", "wrong_product"}:
        db.refresh(item)
        assert item.product_catalog_id == own.id and item.match_method == "invoice_sku"
        visible = catalog(db, has_margin=True)["rows"][0]
        assert visible["aade_cost_net"] == 70 and visible["gross_margin_percent"] == 30
        feed = db.get(SupplierCatalogFeed, item.feed_id)
        apply_catalog(db, feed, [{"supplier_code": own.sku, "supplier_sku": None,
            "ean": own.ean, "name": "Fresh title", "details": {"sell_step": "1"}}])
        db.expire(item)
        assert item.product_catalog_id == own.id and item.match_method == "invoice_sku"


@pytest.mark.parametrize("problem", ["other_supplier", "missing_sku", "leading_zero", "different_hyphen",
    "barcode_as_code", "missing_code", "kg", "missing_unit", "quantity", "cancelled", "credit", "totals", "recipient"])
def test_direct_sku_never_bypasses_product_or_fiscal_guards(db, problem):
    _, supplier, own, item, fiscal = pakketo(db)
    rows = [dict(row) for row in fiscal.raw["invoiceDetails"]]
    if problem == "other_supplier":
        supplier.vat_number = fiscal.issuer_vat = "999218818"
    elif problem == "missing_sku":
        own.sku, own.model = "OTHER", rows[0]["itemCode"]
    elif problem in {"leading_zero", "different_hyphen", "barcode_as_code", "missing_code"}:
        rows[0]["itemCode"] = {"leading_zero": "0499-000039", "different_hyphen": "499000039",
            "barcode_as_code": own.ean, "missing_code": ""}[problem]
    elif problem in {"kg", "missing_unit"}:
        rows[0]["measurementUnit"] = "kg" if problem == "kg" else None
    elif problem == "quantity":
        rows[0]["quantity"] = 0
    elif problem == "cancelled":
        fiscal.is_cancelled = True
    elif problem == "credit":
        fiscal.invoice_type = "5.2"
    elif problem == "totals":
        fiscal.net_value += 1
    elif problem == "recipient":
        fiscal.counterpart_vat = "000000000"
    fiscal.raw = {**fiscal.raw, "invoiceDetails": rows}
    db.commit()
    assert not invoice_preview(db, fiscal.id, supplier.id)["can_import"]
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("conflict", ["target", "conversion"])
def test_prior_verified_mapping_conflict_is_not_overwritten(db, manual, conflict):
    _, supplier, own, _, fiscal = pakketo(db)
    before = invoice_preview(db, fiscal.id, supplier.id)
    other = db.scalar(select(ProductCatalog).where(ProductCatalog.sku == "029-000326"))
    target = other if conflict == "target" else own
    identity = review_identity(own.sku, fiscal.mark, "1", before["source_digest"], True) if manual else "sku:" + own.sku
    db.add(SupplierProductMap(supplier_id=supplier.id, identity_key=identity,
        supplier_code=own.sku, product_catalog_id=target.id, verified=True, status="matched",
        pack_quantity=1, conversion_factor=2 if conflict == "conversion" else 1,
        match_method="aade_manual_reviewed" if manual else "aade_xml_reviewed",
        raw_metadata={"aade_review": {"product_identity": product_identity(target)}}))
    db.commit()
    assert not invoice_preview(db, fiscal.id, supplier.id)["can_import"]


def test_sku_changes_after_preview_cannot_create_or_reassign_costs(db):
    actor, supplier, own, _, fiscal = pakketo(db)
    before = invoice_preview(db, fiscal.id, supplier.id)
    own.sku = "CHANGED"
    db.commit()
    with pytest.raises(ValueError):
        accept_invoice(db, fiscal.id, payload(before), actor)
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_background_retries_old_partial_invoices_without_xml_refresh(db):
    actor, supplier, own, _, fiscal = pakketo(db)
    rows = [dict(row) for row in fiscal.raw["invoiceDetails"]]
    # A second valid SKU is imported while this line has no exact INDE SKU yet.
    own.sku = "FIRST"
    rows[0]["itemCode"] = "FIRST"
    rows.insert(1, {"lineNumber": 3, "itemCode": "499-000039", "quantity": 2,
        "measurementUnit": 1, "netValue": "28.14", "vatAmount": "6.75"})
    fiscal.raw = {**fiscal.raw, "invoiceDetails": rows}
    fiscal.net_value += Decimal("28.14")
    fiscal.vat_amount += Decimal("6.75")
    fiscal.gross_value += Decimal("34.89")
    db.commit()
    auto_policy(db, actor, supplier)
    assert process_aade_costs(db)["status"] == "partial"
    assert process_aade_costs(db) == {"processed": 0}
    fiscal.raw = {**fiscal.raw, "_catalog_cost": {**fiscal.raw["_catalog_cost"],
        "input_revision": "line-costs-v2:old", "next_attempt_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()}}
    second = ProductCatalog(sku="499-000039", name="Restored exact SKU")
    db.add(second)
    db.commit()
    result = process_aade_costs(db)
    assert result["costs_created"] == 1 and result["status"] == "imported"
    assert process_aade_costs(db) == {"processed": 0}
    costs = db.scalars(select(SupplierProductCost).order_by(SupplierProductCost.net_unit_cost)).all()
    assert [(row.product_catalog_id, row.net_unit_cost) for row in costs] == [(second.id, Decimal("14.07")), (own.id, Decimal("70"))]
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierDocumentLine)) == 3


def test_piece_cost_and_sale_step_still_have_distinct_units(db):
    actor, supplier, _, item, fiscal = pakketo(db)
    item.details = {"sell_step": "4"}
    db.commit()
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    row = catalog(db, has_margin=True)["rows"][0]
    assert row["aade_cost_net"] == 70 and row["aade_cost_sale_net"] == 280
    assert row["inde_price"] == 124 and row["gross_margin_percent"] == -180


def test_fee_line_remains_pending_while_exact_sku_cost_is_imported(db):
    actor, supplier, own, _, fiscal = pakketo(db)
    fee = {"lineNumber": 3, "itemCode": "ΤΡΓ", "itemDescr": "Χρέωση Τριγωνικής (αξία)",
        "quantity": 1, "measurementUnit": 1, "netValue": "1.30", "vatAmount": "0.31"}
    db.add(ProductCatalog(sku="ΤΡΓ", name="Not a product"))
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [*fiscal.raw["invoiceDetails"], fee]}
    fiscal.net_value += Decimal("1.30")
    fiscal.vat_amount += Decimal("0.31")
    fiscal.gross_value += Decimal("1.61")
    db.commit()
    result = accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), actor)
    assert result["costs_created"] == result["pending_lines"] == 1
    assert db.scalar(select(SupplierProductCost.product_catalog_id)) == own.id
