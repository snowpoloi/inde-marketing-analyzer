from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (OpenCartOrder, OpenCartOrderProduct, ProductCatalog, SupplierCatalogFeed,
                        SupplierProductCost, SupplierProductMap)
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, validated_cost_rows
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_aade_rules import DIRECT_SKU_SUPPLIERS, product_identity, review_identity
from app.services.supplier_catalog_service import apply_catalog
from app.services.supplier_catalog_orders import product_orders
from app.services.dashboard_service import product_performance
from test_supplier_aade_costs import seed, auto_policy, payload


@pytest.fixture(params=[("094494879", "GL.", "03-8066"), ("998434505", "Lib.", "09-2044")])
def prefixed(db, request):
    vat, prefix, code = request.param
    actor, supplier, own, item, fiscal = seed(db)
    supplier.vat_number = fiscal.issuer_vat = vat
    own.sku, own.model, own.product_id = code, prefix + code, "42"
    own.brand = "Fixture supplier"
    item.supplier_code = item.supplier_sku = code
    item.product_catalog_id, item.match_method = None, "unmatched"
    item.details = {"sale_quantity": "1", "shop_model": prefix + code, "shop_sku": code}
    feed = db.get(SupplierCatalogFeed, item.feed_id)
    feed.adapter = "gloria"
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {**fiscal.raw["invoiceDetails"][0], "itemCode": code}, fiscal.raw["invoiceDetails"][1]]}
    db.commit()
    return actor, supplier, own, item, fiscal


@pytest.mark.parametrize("identity", ["model", "sku"])
@pytest.mark.parametrize("with_xml", [True, False])
def test_prefixed_code_cost_and_order_profit_without_xml_dependency(db, prefixed, identity, with_xml):
    actor, supplier, own, item, fiscal = prefixed
    rule = DIRECT_SKU_SUPPLIERS[supplier.vat_number]
    if identity == "sku":
        own.sku, own.model = own.model, None
    if not with_xml:
        feed = db.get(SupplierCatalogFeed, item.feed_id)
        db.delete(item)
        db.flush()
        db.delete(feed)
    # An unrelated supplier's barcode and bare model must never redirect costs.
    db.add(ProductCatalog(sku="FOREIGN", model=item.supplier_code, ean=own.ean, name="Other supplier"))
    order = OpenCartOrder(order_id="prefix-order", date_added=datetime(2026, 9, 1, tzinfo=timezone.utc),
                          order_status="completed")
    order.products.append(OpenCartOrderProduct(product_id="42", sku=own.sku, model=own.model,
                                               name="Chair", quantity=1, price=100))
    db.add(order)
    db.commit()
    auto_policy(db, actor, supplier, confirm_units=False)
    before = invoice_preview(db, fiscal.id, supplier.id)
    assert before["can_import"] and before["lines"][0]["match_method"] == rule["method"]
    assert process_aade_costs(db)["costs_created"] == 1
    cost = db.scalar(select(SupplierProductCost))
    assert cost.product_catalog_id == own.id and cost.net_unit_cost == Decimal("70")
    assert validated_cost_rows(db, [cost]) == [cost]
    assert process_aade_costs(db) == {"processed": 0}
    rows = product_performance(db, date(2026, 9, 1), date(2026, 9, 1), include_costs=True)
    assert rows[0]["cogs"] == 70 and rows[0]["gross_profit"] == 30
    assert own.price == 124
    if with_xml:
        db.refresh(item)
        assert item.product_catalog_id == own.id
        assert product_orders(db, item.id, fiscal.issue_date, fiscal.issue_date)["rows"][0]["order_id"] == "prefix-order"
        apply_catalog(db, db.get(SupplierCatalogFeed, item.feed_id), [{"supplier_code": item.supplier_code,
            "supplier_sku": item.supplier_code, "name": "Refreshed title", "ean": own.ean,
            "details": {"shop_model": "obsolete XML model", "shop_sku": item.supplier_code, "sale_quantity": "1"}}])
        db.expire(item)
        assert item.product_catalog_id == own.id
        assert invoice_preview(db, fiscal.id, supplier.id)["costed_lines"] == 1
        assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1


@pytest.mark.parametrize("problem", ["no_prefix", "wrong_prefix", "missing_dot", "missing_zero", "ambiguous",
    "barcode", "kg", "missing_unit", "cancelled", "credit", "recipient", "totals"])
def test_prefixed_matching_never_guesses_or_bypasses_fiscal_guards(db, prefixed, problem):
    _, supplier, own, _, fiscal = prefixed
    rows = [dict(row) for row in fiscal.raw["invoiceDetails"]]
    code = rows[0]["itemCode"]
    if problem == "no_prefix":
        own.model = code
    elif problem == "wrong_prefix":
        own.model = "OTHER." + code
    elif problem == "missing_dot":
        own.model = own.model.replace(".", "")
    elif problem == "missing_zero":
        rows[0]["itemCode"] = code.lstrip("0")
    elif problem == "ambiguous":
        db.add(ProductCatalog(sku="CONFLICT", model=own.model, name="Conflicting model"))
    elif problem == "barcode":
        rows[0]["itemCode"] = own.ean
    elif problem in {"kg", "missing_unit"}:
        rows[0]["measurementUnit"] = "kg" if problem == "kg" else None
    elif problem == "cancelled":
        fiscal.is_cancelled = True
    elif problem == "credit":
        fiscal.invoice_type = "5.2"
    elif problem == "recipient":
        fiscal.counterpart_vat = "000000000"
    elif problem == "totals":
        fiscal.net_value += 1
    fiscal.raw = {**fiscal.raw, "invoiceDetails": rows}
    db.commit()
    assert not invoice_preview(db, fiscal.id, supplier.id)["can_import"]
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_prefixed_conflicting_human_mapping_remains_blocked(db, prefixed):
    _, supplier, own, _, fiscal = prefixed
    before = invoice_preview(db, fiscal.id, supplier.id)
    other = ProductCatalog(sku="MANUAL-OTHER", name="Other product")
    db.add(other)
    db.flush()
    code = before["lines"][0]["item_code"]
    db.add(SupplierProductMap(supplier_id=supplier.id,
        identity_key=review_identity(code, fiscal.mark, "1", before["source_digest"], True),
        supplier_code=code, product_catalog_id=other.id, verified=True, status="matched",
        pack_quantity=1, conversion_factor=1, match_method="aade_manual_reviewed",
        raw_metadata={"aade_review": {"product_identity": product_identity(other)}}))
    db.commit()
    assert not invoice_preview(db, fiscal.id, supplier.id)["can_import"]
