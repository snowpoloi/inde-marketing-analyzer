from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import (AADEDocument, IntegrationSetting, ProductCatalog, Supplier, SupplierCatalogFeed,
                        SupplierCatalogProduct, SupplierDocument, SupplierProductCost, User)
from app.schemas.suppliers import SupplierAADEAcceptRequest, SupplierIdentityRequest, SupplierAADEBatchRequest
from app.services.supplier_identity import save_supplier_identity, supplier_identities, registered_supplier_names
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, parse_lines, validated_cost_rows, aade_invoices, import_cost_batch
from app.services.supplier_catalog_pricing import latest_aade_costs
from app.services.supplier_service import supplier_summary
from test_supplier_api import client


def seed(db):
    user = User(email=f"aade-{uuid4()}@example.test", hashed_password="fixture", is_admin=True)
    db.add(user); db.flush()
    identity = save_supplier_identity(db, SupplierIdentityRequest(code="MEGAPAP", name="Supplier company", vat_number="EL 123456789"), user)
    supplier = db.get(Supplier, identity["id"])
    own = ProductCatalog(sku="CH-N5080-GR", name="Chair", price=124, raw={"prices_include_vat":True,"vat_rate":24})
    feed = SupplierCatalogFeed(code="MEGAPAP", name="MEGAPAP", adapter="megapap", encrypted_url="test")
    config = IntegrationSetting(provider="aade", display_name="AADE", config={"vat_number":"802216736"})
    db.add_all([own, feed, config]); db.flush()
    item = SupplierCatalogProduct(feed_id=feed.id, supplier_code="0268292", supplier_sku=own.sku,
        ean="5203266100377", name="Chair", product_catalog_id=own.id, is_current=True, match_method="exact_identifiers", last_seen_at=datetime.now(timezone.utc))
    fiscal = AADEDocument(source_endpoint="RequestDocs", identity_key="invoice-test", mark="400-test",
        issuer_vat=supplier.vat_number, counterpart_vat="802216736", issue_date=date(2026, 9, 1), aa="INV-1", series="A",
        currency="EUR", document_direction="expense", invoice_type="1.1", net_value=145, vat_amount=34.8, gross_value=179.8,
        raw={"record_type":"full_document", "invoiceDetails":[
            {"lineNumber":1,"itemCode":"0268292","itemDescr":"Chair","quantity":2,"measurementUnit":1,"netValue":140,"vatAmount":33.6},
            {"lineNumber":2,"itemDescr":"Shipping","netValue":5,"vatAmount":1.2}]})
    db.add_all([item, fiscal]); db.commit()
    return user, supplier, own, item, fiscal


def payload(preview):
    return SupplierAADEAcceptRequest(supplier_id=preview["supplier_id"], fingerprint=preview["fingerprint"], confirm_products_and_units=True)


def test_identity_registry_uniqueness_and_no_price_changes(db):
    user = SimpleNamespace(id=uuid4())
    save_supplier_identity(db, SupplierIdentityRequest(code="MEGAPAP",name="Legal name",vat_number="EL 012345678"),user)
    assert supplier_identities(db)[0]["vat_number"] == "012345678"
    assert registered_supplier_names(db)["012345678"] == "Legal name"
    with pytest.raises(ValueError, match="already assigned"):
        save_supplier_identity(db, SupplierIdentityRequest(code="OTHER",name="Other",vat_number="012345678"),user)
    with pytest.raises(ValueError, match="9-digit"):
        save_supplier_identity(db, SupplierIdentityRequest(code="OTHER",name="Other",vat_number="000000000"),user)
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_review_import_and_duplicate_mark_cancellation(db):
    user, supplier, own, item, fiscal = seed(db)
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert preview["can_import"], preview
    assert preview["lines"][0]["inde_sku"] == "CH-N5080-GR"
    assert preview["lines"][0]["unit_cost_net"] == Decimal("70")
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    assert accept_invoice(db, fiscal.id, payload(preview), user)["costs_created"] == 1
    assert accept_invoice(db, fiscal.id, payload(preview), user)["duplicate"]
    costs = db.scalars(select(SupplierProductCost)).all()
    assert len(costs) == 1 and costs[0].net_unit_cost == 70 and costs[0].source_type == "aade_invoice"
    assert latest_aade_costs(db, {own.id}, {"MEGAPAP"})[("MEGAPAP",own.id)][0].net_unit_cost == 70
    doc = db.scalar(select(SupplierDocument))
    assert doc.net_shipping_total == 5 and doc.net_products_total == 140
    assert supplier_summary(db,date(2026,9,1),date(2026,9,30))["purchases"] == 140
    assert validated_cost_rows(db,costs) == costs
    fiscal.raw = {**fiscal.raw, "invoiceDetails":[{**fiscal.raw["invoiceDetails"][0],"netValue":150},fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    assert not validated_cost_rows(db,costs)
    assert not latest_aade_costs(db, {own.id}, {"MEGAPAP"})
    assert supplier_summary(db,date(2026,9,1),date(2026,9,30))["purchases"] == 0
    fiscal.is_cancelled = True; db.flush()
    assert not validated_cost_rows(db,costs)
    with pytest.raises(ValueError, match="linked AADE"):
        save_supplier_identity(db, SupplierIdentityRequest(code="MEGAPAP",name="Changed",vat_number="987654321"),user)


@pytest.mark.parametrize("field,value", [("counterpart_vat","other"),("issuer_vat","other"),("currency","USD"),
    ("invoice_type","5.1"),("invoice_type","9.3"),("invoice_type","2.1"),("is_cancelled",True),("mark",None),
    ("document_direction","income"),("gross_value",999)])
def test_unsafe_documents_are_blocked(db, field, value):
    user,supplier,own,item,fiscal = seed(db)
    setattr(fiscal,field,value); db.flush()
    preview = invoice_preview(db,fiscal.id,supplier.id)
    assert not preview["can_import"]
    with pytest.raises(ValueError,match="needs review"):
        accept_invoice(db,fiscal.id,payload(preview),user)
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


@pytest.mark.parametrize("field,value", [("quantity",None),("netValue",None),("netValue","invalid"),("itemCode",None),
    ("measurementUnit",2),("quantity",0),("vatAmount",None),("recType",1),("recType",2),("recType",7)])
def test_missing_line_fields_are_never_zero_or_assumed(db, field, value):
    _,supplier,_,_,fiscal = seed(db)
    fiscal.raw = {**fiscal.raw,"invoiceDetails":[{**fiscal.raw["invoiceDetails"][0],field:value},fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    preview = invoice_preview(db,fiscal.id,supplier.id)
    assert not preview["can_import"]
    assert preview["lines"][0]["reasons"]
    assert preview["lines"][0]["unit_cost_net"] is None


def test_preview_fingerprint_and_xml_ambiguity(db):
    user,supplier,own,item,fiscal = seed(db)
    preview = invoice_preview(db,fiscal.id,supplier.id)
    item.supplier_code = "changed"; db.flush()
    with pytest.raises(ValueError,match="changed"):
        accept_invoice(db,fiscal.id,payload(preview),user)
    assert not invoice_preview(db,fiscal.id,supplier.id)["can_import"]
    item.supplier_code = "0268292"
    db.add(SupplierCatalogProduct(feed_id=item.feed_id,supplier_code="OTHER",supplier_sku="0268292",name="Different code",
        product_catalog_id=None,is_current=True,last_seen_at=datetime.now(timezone.utc))); db.flush()
    assert not invoice_preview(db,fiscal.id,supplier.id)["can_import"]


def test_endpoint_copies_cannot_duplicate_costs(db):
    user,supplier,own,_,fiscal = seed(db)
    copy = AADEDocument(source_endpoint="RequestTransmittedDocs", identity_key="copy-test", mark=fiscal.mark,
        issuer_vat=fiscal.issuer_vat,counterpart_vat=fiscal.counterpart_vat,issue_date=fiscal.issue_date,
        aa=fiscal.aa,series=fiscal.series,currency="EUR",document_direction="expense",invoice_type="1.1",
        net_value=fiscal.net_value,vat_amount=fiscal.vat_amount,gross_value=fiscal.gross_value,raw=fiscal.raw)
    db.add(copy); db.commit()
    first = invoice_preview(db,fiscal.id,supplier.id)
    assert first["can_import"]
    accept_invoice(db,fiscal.id,payload(first),user)
    assert invoice_preview(db,copy.id,supplier.id)["imported"]
    copy.is_cancelled = True; db.flush()
    assert not latest_aade_costs(db,{own.id},{"MEGAPAP"})
    summary = supplier_summary(db,date(2026,9,1),date(2026,9,30))
    assert summary["purchases"] == 0 and summary["freight"] == 0


def test_product_shipping_word_is_not_freight():
    line = parse_lines({"invoiceDetails":[{"itemCode":"CART","itemDescr":"Καρότσι μεταφοράς",
        "quantity":2,"measurementUnit":1,"netValue":"66.23","vatAmount":"15.90"}]})[0]
    assert line["line_type"] == "product" and line["unit_cost_net"] == Decimal("33.1150")


def test_megapap_fiscal_freight_code_is_not_a_product(db):
    user,supplier,_,_,fiscal = seed(db)
    fiscal.raw = {**fiscal.raw,"invoiceDetails":[fiscal.raw["invoiceDetails"][0],
        {**fiscal.raw["invoiceDetails"][1],"itemCode":"ΜΤΦ","itemDescr":"Μεταφορικά πωλήσεων (αξία)","quantity":1,"measurementUnit":1}]}
    db.commit()
    preview=invoice_preview(db,fiscal.id,supplier.id)
    assert preview["can_import"]
    assert preview["lines"][1]["line_type"] == "shipping"
    assert accept_invoice(db,fiscal.id,payload(preview),user)["costs_created"] == 1
    assert db.scalar(select(SupplierDocument.net_shipping_total)) == 5


def test_el_prefixed_fiscal_vat_keeps_catalog_cost(db):
    user,supplier,own,_,fiscal = seed(db)
    fiscal.issuer_vat = "EL" + supplier.vat_number; db.flush()
    preview = invoice_preview(db,fiscal.id,supplier.id)
    assert preview["can_import"]
    accept_invoice(db,fiscal.id,payload(preview),user)
    assert latest_aade_costs(db,{own.id},{"MEGAPAP"})[("MEGAPAP",own.id)][0].net_unit_cost == 70


def test_legacy_invoice_number_blocks_second_import(db):
    _,supplier,_,_,fiscal = seed(db)
    from app.schemas.suppliers import SupplierImportRequest
    from app.services.supplier_service import import_supplier_documents
    request = SupplierImportRequest.model_validate({"supplier":{"code":supplier.code,"name":supplier.name},
        "documents":[{"document_type":"invoice","document_number":fiscal.aa,"document_date":str(fiscal.issue_date),
        "lines":[{"supplier_sku":"CH-N5080-GR","quantity":2,"net_line_total":140}]}]})
    import_supplier_documents(db,request)
    preview = invoice_preview(db,fiscal.id,supplier.id)
    assert not preview["can_import"] and any("another import" in reason for reason in preview["reasons"])


def test_api_requires_admin_and_explicit_review(db):
    user,supplier,own,item,fiscal = seed(db)
    with client(db,True) as http:
        assert http.get("/api/suppliers/identities").status_code == 200
        query=f"supplier_id={supplier.id}&date_from=2026-09-01&date_to=2026-09-30"
        rows=http.get(f"/api/suppliers/aade/invoices?{query}").json()["data"]
        assert rows["total"] == 1
        assert http.get(f"/api/suppliers/aade/invoices?{query}&limit=51").status_code == 422
        preview=http.get(f"/api/suppliers/aade/invoices/{fiscal.id}?supplier_id={supplier.id}").json()["data"]
        response=http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/accept",json={"supplier_id":str(supplier.id),"fingerprint":preview["fingerprint"]})
        assert response.status_code == 409
    with client(db,False) as http:
        assert http.get("/api/suppliers/identities").status_code == 403
        assert http.get(f"/api/suppliers/aade/invoices?{query}").status_code == 403
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def without_unit(fiscal):
    line = {k:v for k,v in fiscal.raw["invoiceDetails"][0].items() if k != "measurementUnit"}
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [line, fiscal.raw["invoiceDetails"][1]]}


def test_missing_unit_requires_explicit_confirmation_and_audit(db):
    user, supplier, own, _, fiscal = seed(db)
    without_unit(fiscal); db.flush()
    unconfirmed = invoice_preview(db, fiscal.id, supplier.id)
    assert unconfirmed["needs_unit_confirmation"] and not unconfirmed["can_import"]
    reviewed = invoice_preview(db, fiscal.id, supplier.id, confirm_missing_units=True)
    assert reviewed["can_import"] and reviewed["lines"][0]["unit_cost_net"] == 70
    assert reviewed["fingerprint"] != unconfirmed["fingerprint"]
    with pytest.raises(ValueError, match="changed"):
        accept_invoice(db, fiscal.id, payload(reviewed), user)
    request = payload(reviewed).model_copy(update={"confirm_missing_units":True})
    assert accept_invoice(db, fiscal.id, request, user)["costs_created"] == 1
    assert own.price == 124
    doc = db.scalar(select(SupplierDocument))
    assert doc.raw_metadata["aade_confirm_missing_units"] is True
    assert str(doc.raw_metadata["aade_reviewed_by"]) == str(user.id)
    assert fiscal.raw["invoiceDetails"][0].get("measurementUnit") is None
    assert latest_aade_costs(db, {own.id}, {supplier.code})[(supplier.code,own.id)][0].net_unit_cost == 70


@pytest.mark.parametrize("field,value", [("measurementUnit",2), ("itemCode","wrong"), ("quantity",0), ("vatAmount",None)])
def test_unit_confirmation_does_not_bypass_other_guards(db, field, value):
    _, supplier, _, _, fiscal = seed(db)
    without_unit(fiscal)
    fiscal.raw = {**fiscal.raw, "invoiceDetails":[{**fiscal.raw["invoiceDetails"][0],field:value},fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    assert not invoice_preview(db,fiscal.id,supplier.id,confirm_missing_units=True)["can_import"]


def batch_payload(supplier, **updates):
    return SupplierAADEBatchRequest(supplier_id=supplier.id,date_from=date(2026,9,1),date_to=date(2026,9,30),
                                    confirm_products_and_units=True, **updates)


def test_batch_import_is_idempotent_and_excludes_freight(db):
    user, supplier, own, _, fiscal = seed(db)
    without_unit(fiscal); db.commit()
    denied = batch_payload(supplier).model_copy(update={"confirm_products_and_units":False})
    with pytest.raises(ValueError,match="Confirm"):
        import_cost_batch(db,denied,user)
    assert import_cost_batch(db,batch_payload(supplier),user)["costs_created"] == 0
    result = import_cost_batch(db,batch_payload(supplier,confirm_missing_units=True),user)
    assert result["costs_created"] == 1 and result["next_offset"] is None
    assert result["rows"][0]["status"] == "imported"
    assert import_cost_batch(db,batch_payload(supplier,confirm_missing_units=True),user)["rows"][0]["status"] == "already_imported"
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1
    assert db.scalar(select(SupplierProductCost.net_unit_cost)) == 70
    assert own.price == 124


def test_batch_is_bounded_and_skips_non_product_records(db):
    user,supplier,_,_,fiscal = seed(db)
    for index in range(6):
        db.add(AADEDocument(source_endpoint="RequestDocs",identity_key=f"batch-{index}",mark=f"batch-{index}",
            issuer_vat=fiscal.issuer_vat,counterpart_vat=fiscal.counterpart_vat,issue_date=fiscal.issue_date,
            aa=str(index),series="B",currency="EUR",document_direction="expense",invoice_type="2.1",
            net_value=fiscal.net_value,vat_amount=fiscal.vat_amount,gross_value=fiscal.gross_value,raw=fiscal.raw))
    db.add(AADEDocument(source_endpoint="RequestMyExpenses",identity_key="book",issuer_vat=fiscal.issuer_vat,
        counterpart_vat=fiscal.counterpart_vat,issue_date=fiscal.issue_date,document_direction="expense",
        raw={"record_type":"book_info"}))
    db.commit()
    first=import_cost_batch(db,batch_payload(supplier),user)
    assert len(first["rows"]) == 5 and first["total"] == 7 and first["next_offset"] == 5
    second=import_cost_batch(db,batch_payload(supplier,offset=5),user)
    assert len(second["rows"]) == 2 and second["next_offset"] is None
    assert all(row["status"] in {"imported","review"} for row in first["rows"] + second["rows"])
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1


def test_batch_api_requires_admin_confirmation_and_bounded_dates(db):
    _,supplier,_,_,_=seed(db)
    body=batch_payload(supplier).model_dump(mode="json")
    with client(db,False) as http:
        assert http.post("/api/suppliers/aade/costs/batch",json=body).status_code == 403
    with client(db,True) as http:
        assert http.post("/api/suppliers/aade/costs/batch",json={**body,"confirm_products_and_units":False}).status_code == 400
        assert http.post("/api/suppliers/aade/costs/batch",json={**body,"date_from":"2020-01-01"}).status_code == 400
        assert http.post("/api/suppliers/aade/costs/batch",json={**body,"offset":-1}).status_code == 422
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
