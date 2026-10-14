from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import ProductCatalog, SupplierCatalogFeed, SupplierDocument, SupplierProductCost
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, validated_cost_rows
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_aade_review import pending_costs
from app.services.supplier_catalog_service import apply_catalog, refresh_state
from test_supplier_aade_costs import seed, auto_policy, payload
from test_supplier_aade_review import another_invoice


def zougris(db, *, with_feed=False, code="41.0151"):
    actor, supplier, own, item, fiscal = seed(db)
    feed = db.get(SupplierCatalogFeed, item.feed_id)
    supplier.code, supplier.vat_number = "AADE_999214660", "999214660"
    own.sku = code
    own.ean = item.ean
    fiscal.issuer_vat = supplier.vat_number
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "itemCode": code}, fiscal.raw["invoiceDetails"][1]]}
    if with_feed:
        feed.code = supplier.code
        item.supplier_code, item.supplier_sku = code, None
        item.product_catalog_id, item.match_method = None, "ambiguous"
    else:
        db.delete(item)
        db.flush()
        db.delete(feed)
    db.commit()
    return actor, supplier, own, item if with_feed else None, fiscal


@pytest.mark.parametrize("code", ["41.0151", "01.0201"])
@pytest.mark.parametrize("with_feed", [False, True])
def test_zougris_exact_sku_costs_work_without_xml_or_barcode_bridge(db, code, with_feed):
    actor, supplier, own, item, fiscal = zougris(db, with_feed=with_feed, code=code)
    db.add(ProductCatalog(sku="SHARED-BARCODE", model=code, ean=own.ean, name="Other chair"))
    db.commit()
    before = invoice_preview(db, fiscal.id, supplier.id)
    assert before["can_import"] and before["lines"][0]["match_method"] == "aade_zougris_sku"
    assert before["lines"][0]["inde_sku"] == code
    assert accept_invoice(db, fiscal.id, payload(before), actor)["costs_created"] == 1
    cost = db.scalar(select(SupplierProductCost))
    assert cost.product_catalog_id == own.id and cost.net_unit_cost == 70
    assert cost.source_type == "aade_invoice" and cost.raw_metadata["aade_match_method"] == "aade_zougris_sku"
    assert validated_cost_rows(db, [cost]) == [cost]
    assert accept_invoice(db, fiscal.id, payload(before), actor)["duplicate"]
    assert pending_costs(db, fiscal.issue_date, fiscal.issue_date, supplier_id=supplier.id)["total"] == 0
    if item:
        assert item.product_catalog_id == own.id and item.match_method == "invoice_sku"
        # Even a future XML adapter must not replace an exact confirmed SKU with a shared barcode.
        feed = db.get(SupplierCatalogFeed, item.feed_id)
        apply_catalog(db, feed, [{"supplier_code": code, "ean": own.ean, "name": "Fresh table"}])
        db.expire(item)
        assert item.product_catalog_id == own.id and item.match_method == "invoice_sku"


def test_no_xml_worker_wakes_old_zougris_reviews_and_updates_revision(db):
    actor, supplier, own, _, fiscal = zougris(db)
    auto_policy(db, actor, supplier, confirm_units=False)
    fiscal.raw = {**fiscal.raw, "_catalog_cost": {"input_revision": "line-costs-v2:old",
        "next_attempt_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()}}
    db.commit()
    before = refresh_state(db)
    assert process_aade_costs(db)["costs_created"] == 1
    assert process_aade_costs(db) == {"processed": 0}
    after = refresh_state(db)
    assert f"supplier:{supplier.code}" not in before["cost_revisions"]
    assert after["cost_revisions"][f"supplier:{supplier.code}"] is not None
    assert own.price == 124
    second = another_invoice(db, fiscal, raw={**fiscal.raw, "_catalog_cost": {}})
    db.commit()
    assert process_aade_costs(db)["costs_created"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 2
    second.is_cancelled = True
    db.flush()
    assert len(validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())) == 1


@pytest.mark.parametrize("problem", ["other_supplier", "missing_sku", "missing_zero", "missing_dot",
    "barcode_code", "missing_unit", "kilograms", "invalid_quantity", "cancelled", "credit", "totals", "inactive_actor", "disabled_feed"])
def test_zougris_worker_preserves_guards_and_never_guesses(db, problem):
    actor, supplier, own, item, fiscal = zougris(db, with_feed=problem == "disabled_feed", code="01.0201")
    rows = [dict(row) for row in fiscal.raw["invoiceDetails"]]
    if problem == "other_supplier":
        supplier.vat_number = fiscal.issuer_vat = "123456789"
    elif problem == "missing_sku":
        own.sku, own.model = "OTHER", rows[0]["itemCode"]
    elif problem in {"missing_zero", "missing_dot", "barcode_code"}:
        rows[0]["itemCode"] = {"missing_zero": "1.0201", "missing_dot": "010201", "barcode_code": own.ean}[problem]
    elif problem in {"missing_unit", "kilograms"}:
        rows[0]["measurementUnit"] = None if problem == "missing_unit" else "kg"
    elif problem == "invalid_quantity":
        rows[0]["quantity"] = 0
    elif problem == "cancelled":
        fiscal.is_cancelled = True
    elif problem == "credit":
        fiscal.invoice_type = "5.2"
    elif problem == "totals":
        fiscal.net_value += 1
    elif problem == "inactive_actor":
        actor.is_active = False
    elif problem == "disabled_feed":
        db.get(SupplierCatalogFeed, item.feed_id).is_enabled = False
    fiscal.raw = {**fiscal.raw, "invoiceDetails": rows}
    db.commit()
    auto_policy(db, actor, supplier, confirm_units=False)
    process_aade_costs(db)
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_zougris_unknown_item_does_not_block_other_invoice_lines(db):
    actor, supplier, own, _, fiscal = zougris(db)
    rows = [*fiscal.raw["invoiceDetails"], {"lineNumber": 3, "itemCode": "UNKNOWN",
        "quantity": 1, "measurementUnit": 1, "netValue": 30, "vatAmount": "7.20"}]
    fiscal.raw = {**fiscal.raw, "invoiceDetails": rows}
    fiscal.net_value += 30
    fiscal.vat_amount += Decimal("7.20")
    fiscal.gross_value += Decimal("37.20")
    db.commit()
    auto_policy(db, actor, supplier)
    first = process_aade_costs(db)
    assert first["status"] == "partial" and first["costs_created"] == 1
    new = ProductCatalog(sku="UNKNOWN", name="Restored table")
    db.add(new)
    auto_policy(db, actor, supplier)
    assert process_aade_costs(db)["costs_created"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 2
