from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.db.session import get_db
from app.models import AADEDocument, ProductCatalog
from app.services import dashboard_service
from app.services.dashboard_service import aade_document_ledger, aade_report, product_performance
from app.services.supplier_service import _catalog_lookup, product_profitability
from app.services.supplier_costing import normalize_identifier
from test_supplier_integration import sale, seed


START, END = date(2026, 8, 1), date(2026, 8, 31)


def capture(db, callback):
    statements = []
    def listen(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listen)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", listen)


def fiscal(db, direction, kind, gross, count=1, cancelled=False):
    row = AADEDocument(source_endpoint="RequestDocs", identity_key=str(uuid4()),
        issue_date=START, document_direction=direction, invoice_type="1.1",
        net_value=Decimal(str(gross)) / Decimal("1.24"), vat_amount=Decimal(str(gross)) * Decimal("24") / Decimal("124"),
        gross_value=Decimal(str(gross)), is_cancelled=cancelled,
        raw={"record_type": kind, "document_count": count,
             "invoiceDetails": [{"description": "A real product", "quantity": 2, "netValue": 20, "vatAmount": 4.8}],
             "unused": "large payload" * 10000})
    db.add(row)
    db.flush()
    return row


def test_fiscal_report_keeps_totals_and_does_not_run_other_audit_sections(db, monkeypatch):
    fiscal(db, "income", "full_document", 124)
    fiscal(db, "income", "book_info", 999)
    fiscal(db, "income", "cancellation", 124, cancelled=True)
    fiscal(db, "expense", "book_info", 248, count=3)
    def forbidden(*args, **kwargs):
        raise AssertionError("Unrelated audit section was executed")
    for name in ("_product_audit", "_campaign_audit", "_tracking_audit", "_operations_audit"):
        monkeypatch.setattr(dashboard_service, name, forbidden)
    result, statements = capture(db, lambda: aade_report(db, START, END))
    summary = result["aade"]["summary"]
    assert summary["income_gross"] == 124
    assert summary["income_documents"] == 2
    assert summary["expense_gross"] == 248
    assert summary["expense_documents"] == 3
    assert summary["cancelled_documents"] == 1
    assert summary["income_vat"] == 24 and summary["expense_vat"] == 48
    assert not any("FROM product_catalog" in sql for sql in statements)
    fiscal_sql = next(sql for sql in statements if "FROM aade_documents" in sql)
    assert "jsonb_build_object" in fiscal_sql
    assert "invoiceDetails" not in fiscal_sql
    assert "aade_documents.raw," not in fiscal_sql
    assert result["aade"]["documents"][0]["documents"] in (2, 3)


def test_fiscal_report_endpoint_is_authenticated_and_preserves_detail_exports(db):
    doc = fiscal(db, "expense", "full_document", 24.8)
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    with TestClient(application) as http:
        assert http.get("/api/dashboard/aade-report").status_code == 401
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
        response = http.get("/api/dashboard/aade-report?date_from=2026-08-01&date_to=2026-08-31")
        assert response.status_code == 200
        assert response.json()["data"]["aade"]["summary"]["expense_gross"] == 24.8
    ledger = aade_document_ledger(db, START, END)
    assert ledger["rows"][0]["identity_key"] == doc.identity_key
    assert ledger["rows"][0]["line_items"][0]["description"] == "A real product"
    assert ledger["rows"][0]["line_items"][0]["quantity"] == 2


def test_profitability_keeps_legacy_barcode_fallback_without_full_catalog_payloads(db):
    product = seed(db)
    product.raw = {"ean": "EAN-OLD", "upc": "UPC-OLD", "description": "large payload" * 10000}
    sale(db, raw={"prices_include_vat": True, "vat_rate": 24, "ean": "EAN-OLD"})
    db.flush()
    db.expunge_all()
    projected = []
    original = _catalog_lookup
    def inspect_catalog(products):
        projected.extend(products)
        return original(products)
    from unittest.mock import patch
    with patch("app.services.supplier_service._catalog_lookup", side_effect=inspect_catalog):
        rows, statements = capture(db, lambda: product_profitability(db, START, END, None))
    assert rows[0]["name"] == "Chair" and rows[0]["net_sales"] == 12.8226
    assert rows[0]["cogs"] is None
    assert projected[0].raw == {"ean": "EAN-OLD", "upc": "UPC-OLD"}
    assert original(projected)[("ean", normalize_identifier("EAN-OLD"))][0].sku == "INDE-1"
    catalog_sql = next(sql for sql in statements if "FROM product_catalog" in sql)
    assert "jsonb_build_object" in catalog_sql and "CASE WHEN" in catalog_sql
    assert "product_catalog.raw," not in catalog_sql


def test_product_report_fetches_only_report_skus_without_raw(db):
    seed(db)
    db.add(ProductCatalog(sku="UNSOLD", name="Never sold", raw={"description": "unused" * 10000}))
    sale(db)
    db.flush()
    db.expunge_all()
    rows, statements = capture(db, lambda: product_performance(db, START, END))
    assert rows[0]["sku"] == "INDE-1"
    catalog_sql = next(sql for sql in statements if "FROM product_catalog" in sql)
    assert "product_catalog.sku IN" in catalog_sql
    assert "product_catalog.raw" not in catalog_sql


def test_empty_profitability_does_not_load_catalog(db):
    rows, statements = capture(db, lambda: product_profitability(db, START, END, None))
    assert rows == []
    assert not any("FROM product_catalog" in sql for sql in statements)


def test_profitability_without_barcode_sales_never_reads_catalog_raw(db):
    seed(db)
    sale(db)
    db.flush()
    db.expunge_all()
    rows, statements = capture(db, lambda: product_profitability(db, START, END, None))
    assert rows[0]["net_sales"] == 12.8226
    catalog_sql = next(sql for sql in statements if "FROM product_catalog" in sql)
    assert "product_catalog.raw" not in catalog_sql
