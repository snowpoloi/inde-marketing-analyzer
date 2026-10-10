from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.orders import router as orders_router
from app.api.routes.supplier_catalog import router as catalog_router
from app.db.session import get_db
from app.models import AADEDocument, SupplierProductCost
from app.services.supplier_aade_jobs import process_aade_costs
from app.services.supplier_catalog_invoices import product_invoices
from test_supplier_aade_costs import seed, auto_policy
from test_supplier_catalog_orders import order


def setup_costs(db):
    user, supplier, own, item, fiscal = seed(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["costs_created"] == 1
    return supplier, own, item, fiscal


def api_client(db, admin=True):
    app = FastAPI()
    for router in (catalog_router, dashboard_router, orders_router):
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=admin)
    return TestClient(app)


def test_invoice_sources_current_history_paging_and_no_private_urls(db):
    supplier, own, item, fiscal = setup_costs(db)
    older = AADEDocument(source_endpoint="RequestDocs", identity_key="older-invoice", mark="OLDER",
        issuer_vat=fiscal.issuer_vat, counterpart_vat=fiscal.counterpart_vat, issue_date=date(2026, 8, 1),
        series="A", aa="OLDER-1", currency="EUR", document_direction="expense", invoice_type="1.1",
        net_value=fiscal.net_value, vat_amount=fiscal.vat_amount, gross_value=fiscal.gross_value,
        raw={key:value for key,value in fiscal.raw.items() if key != "_catalog_cost"})
    db.add(older); db.flush()
    assert process_aade_costs(db)["costs_created"] == 1
    result = product_invoices(db, item.id, limit=1)
    assert result["total"] == 2 and len(result["rows"]) == 1
    current = result["rows"][0]
    assert current["document_id"] == str(fiscal.id) and current["current"]
    assert current["number"] == "A / INV-1"
    assert current["quantity"] == 2 and current["unit_cost_min"] == current["unit_cost_max"] == 70
    assert set(current) == {"document_id", "date", "number", "mark", "quantity", "unit_cost_min", "unit_cost_max", "current"}
    assert not product_invoices(db, item.id, offset=1, limit=1)["rows"][0]["current"]
    assert not product_invoices(db, item.id, offset=2)["rows"]
    item.product_catalog_id = None; db.flush()
    assert product_invoices(db, item.id)["total"] == 0


def test_invoice_sources_exclude_cancelled_changed_unverified_and_other_suppliers(db):
    supplier, own, item, fiscal = setup_costs(db)
    cost = db.scalar(select(SupplierProductCost))
    assert product_invoices(db, item.id)["total"] == 1
    for attribute, bad, good in [("source_type", "gmail_invoice", "aade_invoice"),
                                 ("source_confidence", 0.8, 1), ("status", "void", "active")]:
        setattr(cost, attribute, bad); db.flush()
        assert product_invoices(db, item.id)["total"] == 0
        setattr(cost, attribute, good); db.flush()
    fiscal.is_cancelled = True; db.flush()
    assert product_invoices(db, item.id)["total"] == 0
    fiscal.is_cancelled = False
    original = fiscal.raw
    fiscal.raw = {**original, "invoiceDetails": []}; db.flush()
    assert product_invoices(db, item.id)["total"] == 0
    fiscal.raw = original; db.flush()
    supplier.code = "OTHER"; db.flush()
    assert product_invoices(db, item.id)["total"] == 0


def test_multiple_cost_lines_are_one_invoice_and_ambiguous_match_is_empty(db):
    user, supplier, own, item, fiscal = seed(db)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [
        {"lineNumber":1,"itemCode":"0268292","itemDescr":"Chair","quantity":1,"measurementUnit":1,"netValue":70,"vatAmount":16.8},
        {"lineNumber":2,"itemCode":"0268292","itemDescr":"Chair","quantity":1,"measurementUnit":1,"netValue":70,"vatAmount":16.8},
        {"lineNumber":3,"itemDescr":"Shipping","netValue":5,"vatAmount":1.2}]}
    db.flush(); auto_policy(db, user, supplier)
    assert process_aade_costs(db)["costs_created"] == 2
    result = product_invoices(db, item.id)
    assert result["total"] == 1 and result["rows"][0]["quantity"] == 2
    assert result["rows"][0]["current"]
    item.match_method = "ambiguous"; db.flush()
    assert product_invoices(db, item.id)["total"] == 0


def test_invoice_list_and_exact_details_api_validation_permissions(db):
    supplier, own, item, fiscal = setup_costs(db)
    order(db, "ORDER-1", product_id=own.product_id, quantity=2)
    with api_client(db) as client:
        path = f"/api/supplier-catalog/products/{item.id}/invoices"
        assert client.get(path).json()["total"] == 1
        assert client.get(path + "?offset=-1").status_code == 422
        assert client.get(path + "?limit=101").status_code == 422
        assert client.get(f"/api/supplier-catalog/products/{uuid4()}/invoices").status_code == 404
        response = client.get(f"/api/dashboard/aade-documents/{fiscal.id}")
        assert response.status_code == 200
        invoice = response.json()["data"]
        assert invoice["mark"] == fiscal.mark and invoice["id"] == str(fiscal.id)
        assert invoice["line_items"][0]["item_code"] == "0268292"
        assert client.get(f"/api/dashboard/aade-documents/{uuid4()}").status_code == 404
        assert client.get("/api/dashboard/aade-documents/invalid").status_code == 422
        detail = client.get("/api/orders/detail/ORDER-1").json()["data"]
        assert detail["order_id"] == "ORDER-1" and detail["lines"][0]["quantity"] == 2
        assert client.get("/api/orders/detail/unknown").status_code == 404
    with api_client(db, admin=False) as client:
        assert client.get(path).status_code == 403
        assert client.get("/api/orders/detail/ORDER-1").status_code == 403


def test_exact_expense_detail_does_not_load_unrelated_orders(db):
    from sqlalchemy import event
    _, _, _, fiscal = setup_costs(db)
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        with api_client(db) as client:
            assert client.get(f"/api/dashboard/aade-documents/{fiscal.id}").status_code == 200
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert not any("FROM opencart_orders" in statement for statement in statements)
