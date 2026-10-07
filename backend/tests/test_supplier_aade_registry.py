from datetime import date
from types import SimpleNamespace
from uuid import uuid4
from hashlib import sha256

import pytest
from sqlalchemy import event, func, select

from app.models import AADEDocument, IntegrationSetting, Supplier, SupplierDocument, SupplierProductCost
from app.schemas.suppliers import SupplierIdentityRequest
from app.services.supplier_identity import aade_supplier_registry, import_aade_suppliers, save_supplier_identity
from app.services.supplier_aade_costs import aade_invoices, invoice_preview
from app.services.supplier_service import supplier_performance, unmatched_products
from test_supplier_api import client

START, END = date(2026, 9, 1), date(2026, 9, 30)
USER = SimpleNamespace(id=uuid4())


def own(db):
    db.add(IntegrationSetting(provider="aade", display_name="AADE", config={"vat_number":"802216736"}))
    db.flush()


def document(db, vat="123456789", name="Supplier company", **changes):
    raw = {"record_type":"full_document", "issuer":{"name":name}} if name else {"record_type":"full_document"}
    values = dict(source_endpoint="RequestDocs", identity_key=str(uuid4()), mark=str(uuid4()),
                  issuer_vat=vat, counterpart_vat="802216736", issue_date=START, document_direction="expense",
                  invoice_type="1.1", aa="1", currency="EUR", net_value=100, vat_amount=24, gross_value=124, raw=raw)
    values.update(changes)
    row = AADEDocument(**values); db.add(row); db.flush()
    return row


def test_discovery_deduplicates_marks_preserves_existing_and_creates_no_costs(db):
    own(db)
    saved = save_supplier_identity(db, SupplierIdentityRequest(code="MEGAPAP", name="Verified legal name", vat_number="123456789"), USER)
    original = document(db, name="Other label from AADE")
    document(db, vat="EL 123456789", mark=original.mark, raw={"record_type":"book_info", "counterpartName":"Other label from AADE"})
    document(db, vat="987654321", name="Second supplier", issue_date=date(2026, 8, 1))
    document(db, vat="012345678", name=None)
    before = [(row.identity_key, row.raw) for row in db.scalars(select(AADEDocument))]
    registry = aade_supplier_registry(db, START, END)
    rows = {row["vat_number"]:row for row in registry["rows"]}
    assert len(rows) == 3
    assert rows["123456789"]["documents"] == rows["123456789"]["period_documents"] == 1
    assert rows["123456789"]["id"] == saved["id"] and rows["123456789"]["code"] == "MEGAPAP"
    assert rows["123456789"]["name"] == "Verified legal name"
    assert rows["987654321"]["documents"] == 1 and rows["987654321"]["period_documents"] == 0
    assert rows["012345678"]["name_pending"] and rows["012345678"]["name"] == "AFM 012345678"
    result = import_aade_suppliers(db, USER)
    assert result["created"] == 2 and result["existing"] == 1
    assert import_aade_suppliers(db, USER)["created"] == 0
    assert db.scalar(select(func.count()).select_from(Supplier)) == 3
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 0
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    assert before == [(row.identity_key, row.raw) for row in db.scalars(select(AADEDocument))]
    assert db.get(Supplier, saved["id"]).name == "Verified legal name"


def test_invalid_self_and_other_recipient_records_are_not_suppliers(db):
    own(db)
    document(db, vat="802216736")
    document(db, vat="000000000")
    document(db, vat=None)
    document(db, vat="invalid")
    document(db, vat="123456789", counterpart_vat="other")
    document(db, document_direction="income")
    document(db, raw={"record_type":"cancellation"})
    registry = aade_supplier_registry(db, START, END)
    assert registry["rows"] == [] and registry["skipped_records"] == 6
    assert import_aade_suppliers(db, USER)["created"] == 0


def test_names_from_book_and_headers_and_ambiguous_names_need_review(db):
    own(db)
    document(db, vat="123456789", raw={"record_type":"book_info", "issuerName":"INDE", "counterpartCompanyName":"Book supplier"})
    document(db, vat="987654321", raw={"record_type":"full_document", "invoiceHeader":{"issuer":{"legalName":"Header company"}}})
    document(db, vat="012345678", name="Company A")
    document(db, vat="012345678", name="Company B")
    rows = {row["vat_number"]:row for row in aade_supplier_registry(db, START, END)["rows"]}
    assert rows["123456789"]["name"] == "Book supplier"
    assert rows["987654321"]["name"] == "Header company"
    assert rows["012345678"]["name_pending"] and rows["012345678"]["aade_name"] is None
    assert import_aade_suppliers(db, USER)["created"] == 3


def test_pending_name_enrichment_does_not_replace_manual_name(db):
    own(db)
    fiscal = document(db, name=None)
    import_aade_suppliers(db, USER)
    supplier = db.scalar(select(Supplier))
    assert supplier.raw_metadata["name_pending"]
    fiscal.raw = {"issuer":{"name":"Now available"}, "record_type":"full_document"}
    db.flush()
    assert import_aade_suppliers(db, USER)["names_updated"] == 1
    save_supplier_identity(db, SupplierIdentityRequest(code=supplier.code, name="Manually verified", vat_number=supplier.vat_number), USER)
    fiscal.raw = {"issuer":{"name":"Later different name"}, "record_type":"full_document"}; db.flush()
    assert import_aade_suppliers(db, USER)["names_updated"] == 0
    assert supplier.name == "Manually verified"


def test_duplicate_registered_afm_and_code_conflicts_are_never_merged(db):
    own(db)
    document(db)
    db.add_all([Supplier(code="ONE", name="One", vat_number="123456789"),
                Supplier(code="TWO", name="Two", vat_number="EL123456789")])
    document(db, vat="987654321")
    db.add(Supplier(code="AADE_987654321", name="Another company", vat_number="012345678")); db.flush()
    result = import_aade_suppliers(db, USER)
    assert result["conflicts"] == 2 and result["created"] == 0
    rows = {row["vat_number"]:row for row in aade_supplier_registry(db, START, END)["rows"]}
    assert rows["123456789"]["identity_conflict"] and rows["123456789"]["id"] is None


def test_country_identity_prevents_foreign_vat_collision_and_invoice_access(db):
    own(db)
    domestic = document(db, name="Greek company")
    foreign = document(db, raw={"record_type":"full_document", "issuer":{"country":"DE", "name":"German company"}})
    book = document(db, mark=foreign.mark, raw={"record_type":"book_info", "issuer":{"country":"GR"}, "counterpart":{"country":"DE", "name":"German company"}})
    assert import_aade_suppliers(db, USER)["created"] == 2
    supplier = db.scalar(select(Supplier).where(Supplier.vat_number=="DE123456789"))
    listing = aade_invoices(db, supplier.id, START, END, 0, 50)
    assert {row["id"] for row in listing["rows"]} == {str(foreign.id), str(book.id)}
    greek = db.scalar(select(Supplier).where(Supplier.vat_number=="123456789"))
    assert [row["id"] for row in aade_invoices(db, greek.id, START, END, 0, 50)["rows"]] == [str(domestic.id)]
    preview = invoice_preview(db, foreign.id, supplier.id)
    assert not any("Issuer AFM" in reason for reason in preview["reasons"])
    assert any("Issuer AFM" in reason for reason in invoice_preview(db, domestic.id, supplier.id)["reasons"])
    saved = save_supplier_identity(db, SupplierIdentityRequest(code=supplier.code, name="Verified German company", vat_number=supplier.vat_number), USER)
    assert saved["vat_number"] == "DE123456789"


def test_registry_requires_own_afm_and_admin_access(db):
    document(db)
    with pytest.raises(ValueError, match="INDE AFM"):
        import_aade_suppliers(db, USER)
    assert db.scalar(select(func.count()).select_from(Supplier)) == 0
    own(db)
    with client(db, True) as http:
        assert http.get("/api/suppliers/aade/suppliers?date_from=2026-09-01&date_to=2026-09-30").status_code == 200
        assert http.get("/api/suppliers/aade/suppliers?date_from=2026-09-30&date_to=2026-09-01").status_code == 400
        assert http.post("/api/suppliers/aade/suppliers/import").json()["data"]["created"] == 1
    with client(db, False) as http:
        assert http.get("/api/suppliers/aade/suppliers?date_from=2026-09-01&date_to=2026-09-30").status_code == 403
        assert http.post("/api/suppliers/aade/suppliers/import").status_code == 403


def test_large_invoice_identity_is_expanded_once_without_returning_product_payload(db):
    own(db)
    raw = {"record_type": "full_document", "Issuer": {"country": "GR", "legalName": "Large invoice company"},
           "invoiceDetails": [{"description": sha256(str(i).encode()).hexdigest(), "netValue": i}
                              for i in range(5000)]}
    document(db, raw=raw)
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        rows = aade_supplier_registry(db, START, END)["rows"]
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert rows[0]["name"] == "Large invoice company"
    discovery = next(sql for sql in statements if "jsonb_each" in sql)
    assert discovery.count("jsonb_each") == 1
    assert "jsonb_build_object" not in discovery
    assert "invoiceDetails" not in str(rows)


def test_supplier_page_does_not_scan_catalog_when_no_mappings_exist(db):
    db.add_all([Supplier(code=f"SUPPLIER_{i}", name=f"Company {i}") for i in range(54)])
    db.flush()
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        assert unmatched_products(db) == []
        rows = supplier_performance(db, START, END)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert len(rows) == 54
    assert all(row["purchases"] == 0 and row["orders"] == 0 for row in rows)
    assert not any("FROM product_catalog" in statement for statement in statements)
