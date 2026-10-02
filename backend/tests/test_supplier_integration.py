from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.models import OpenCartOrder, OpenCartOrderProduct, ProductCatalog, SupplierDocument, SupplierProductCost, SupplierProductMap, User
from app.schemas.suppliers import SupplierImportRequest, VerifySupplierMappingRequest
from app.services.dashboard_service import product_performance
from app.services.supplier_service import import_supplier_documents, product_profitability, supplier_performance, verify_supplier_mapping


def payload(number="INV1", day="2026-07-01", cost="8.20", document_type="invoice", shipping="4.90", sku="GP041-0025,4"):
    return SupplierImportRequest.model_validate({"supplier": {"code": "MEGAPAP", "name": "MEGAPAP"},
        "documents": [{"document_type": document_type, "document_number": number, "document_date": day,
        "supplier_order_id": "PO1", "lines": [
            {"supplier_sku": sku, "supplier_code": "0212605", "description": "Chair", "quantity": 1,
             "unit_price_before_discount": cost, "vat_rate": 24},
            {"line_type": "shipping", "quantity": 0, "net_line_total": shipping, "vat_rate": 24}]}]})


def seed(db):
    product = ProductCatalog(sku="INDE-1", product_id="1", model="GP041-0025,4", name="Chair")
    db.add(product)
    db.flush()
    return product


def sale(db, order_id="1", day="2026-08-15", name="Chair", raw=None):
    order = OpenCartOrder(order_id=order_id, date_added=datetime.fromisoformat(day).replace(tzinfo=timezone.utc), order_status="completed", raw={})
    order.products.append(OpenCartOrderProduct(product_id="1", sku="INDE-1", model="GP041-0025,4", name=name,
        quantity=1, price=D("15.90"), raw=raw or {"prices_include_vat": True, "vat_rate": 24}))
    db.add(order)
    db.flush()


def test_idempotency_shipping_and_historical_sales(db):
    seed(db)
    first = import_supplier_documents(db, payload())
    assert first["matched_lines"] == 1
    assert import_supplier_documents(db, payload())["duplicate"]
    renamed = payload()
    renamed.filename = "renamed.json"
    assert import_supplier_documents(db, renamed)["documents_skipped"] == 1
    import_supplier_documents(db, payload("INV2", "2026-09-01", "8.50", shipping="99"))
    import_supplier_documents(db, payload("INV3", "2026-10-02", "8.73", shipping="200"))
    sale(db)
    sale(db, "2", "2026-09-15")
    rows = product_profitability(db, date(2026, 8, 1), date(2026, 9, 30), ["completed"])
    assert len(rows) == 1
    assert rows[0]["cogs"] == 16.7
    assert rows[0]["current_unit_cogs"] == 8.5
    assert {source["unit_cost"] for source in rows[0]["cost_provenance"]} == {8.2, 8.5}
    assert rows[0]["gross_profit"] == pytest.approx(25.6452 - 16.7)
    assert product_profitability(db, date(2026, 8, 1), date(2026, 9, 30), []) == []
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 3


def test_duplicate_conflict_is_rejected(db):
    seed(db)
    import_supplier_documents(db, payload())
    with pytest.raises(ValueError, match="different content"):
        import_supplier_documents(db, payload(cost="9"))
    db.rollback()
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 1


def test_realized_purchases_do_not_include_proforma_or_pricelist(db):
    seed(db)
    for kind, number in [("invoice", "INV1"), ("proforma", "PRO1"), ("supplier_order", "PO1"), ("pricelist", "PRICE1")]:
        import_supplier_documents(db, payload(number=number, document_type=kind))
    import_supplier_documents(db, payload(number="CR1", document_type="credit_note", cost="1", shipping="0"))
    row = supplier_performance(db, date(2026, 7, 1), date(2026, 7, 31))[0]
    assert row["purchases"] == 7.2
    assert row["freight"] == 4.9
    assert row["orders"] == 1


def test_no_future_cost_and_no_fuzzy_assignment(db):
    seed(db)
    import_supplier_documents(db, payload(day="2026-09-01", sku="NOT-IN-STORE"))
    mapping = db.scalar(select(SupplierProductMap))
    assert mapping.status == "unmatched"
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    sale(db)
    row = product_profitability(db, date(2026, 8, 1), date(2026, 8, 31), None)[0]
    assert row["cogs"] is None
    assert row["gross_profit"] is None


def test_mapping_correction_keeps_immutable_cost_values(db):
    product = seed(db)
    import_supplier_documents(db, payload())
    mapping = db.scalar(select(SupplierProductMap))
    user = User(email="supplier-test@example.com", hashed_password="not-a-real-password", is_admin=True)
    db.add(user)
    db.flush()
    result = verify_supplier_mapping(db, mapping.id, VerifySupplierMappingRequest(product_catalog_id=product.id, conversion_factor=2), user)
    assert result["costs_created"] == 1
    costs = list(db.scalars(select(SupplierProductCost)).all())
    assert {(cost.status, cost.net_unit_cost) for cost in costs} == {("superseded", D("8.2")), ("active", D("4.1"))}
    assert mapping.raw_metadata["verification_audit"][0]["previous_factor"] == "1.000000"
    assert verify_supplier_mapping(db, mapping.id, VerifySupplierMappingRequest(product_catalog_id=product.id, conversion_factor=2), user)["costs_created"] == 0


def test_product_labels_do_not_duplicate_profitability(db):
    seed(db)
    import_supplier_documents(db, payload())
    sale(db, name="Old Chair")
    sale(db, "2", name="New Chair")
    rows = product_performance(db, date(2026, 8, 1), date(2026, 8, 31), include_costs=True)
    assert len(rows) == 2
    assert sum(row["cogs"] for row in rows) == 16.4
    legacy = product_performance(db, date(2026, 8, 1), date(2026, 8, 31))
    assert sum(row["revenue"] for row in legacy) == 31.8
    assert all(row["cogs"] is None for row in legacy)


def test_header_reconciliation_rolls_back(db):
    seed(db)
    request = payload()
    request.documents[0].gross_total = D("999")
    with pytest.raises(ValueError, match="reconcile"):
        import_supplier_documents(db, request)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 0


def test_description_only_mappings_do_not_leak_to_other_documents(db):
    from app.schemas.suppliers import SupplierDocumentLineInput
    seed(db)
    for number in ("INV1", "INV2"):
        request = payload(number=number)
        request.documents[0].lines[0] = SupplierDocumentLineInput(description="Generic chair", quantity=1, unit_price_before_discount=8)
        import_supplier_documents(db, request)
    assert db.scalar(select(func.count()).select_from(SupplierProductMap)) == 2
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_partial_returns_coupon_allocation_and_unknown_refund(db):
    seed(db)
    import_supplier_documents(db, payload())
    order = OpenCartOrder(order_id="returns", date_added=datetime(2026, 8, 15, tzinfo=timezone.utc), order_status="completed", raw={"coupon_total": -4})
    for index, returned in enumerate((1, 0)):
        order.products.append(OpenCartOrderProduct(product_id="1", sku="INDE-1", name=f"Chair {index}", quantity=2, price=10, raw={"returned_quantity": returned}))
    db.add(order)
    db.flush()
    rows = product_profitability(db, date(2026, 8, 1), date(2026, 8, 31), None)
    assert sum(row["net_sales"] for row in rows) == 27
    assert sum(row["cogs"] for row in rows) == pytest.approx(24.6)
    order.raw = {"refund_total": 4}
    db.flush()
    assert all(row["net_sales"] is None and row["gross_profit"] is None for row in product_profitability(db, date(2026, 8, 1), date(2026, 8, 31), None))
