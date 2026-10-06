import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.connectors.supplier_gmail import GmailReadError, MAILBOX, READONLY_SCOPE, SupplierGmailReader, decode_body
from app.core.config import settings
from app.models import ProductCatalog, Supplier, SupplierDocument, SupplierGmailSource, SupplierImportBatch, SupplierProductCost, SupplierProductMap, SupplierShippingCost, User
from app.schemas.suppliers import SupplierGmailReviewRequest, SupplierGmailSyncRequest, VerifySupplierMappingRequest
from app.services.supplier_gmail_service import review_gmail_source, stage_source, sync_supplier_gmail
from app.services.supplier_service import unmatched_products, verify_supplier_mapping
from app.supplier_parsers.megapap import MegapapParser

HTML = (Path(__file__).parent / "fixtures/megapap_order.html").read_bytes()


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.setattr(settings, "supplier_gmail_enabled", True)
    monkeypatch.setattr(settings, "supplier_gmail_client_id", "test-client")
    monkeypatch.setattr(settings, "supplier_gmail_client_secret", "test-placeholder")
    monkeypatch.setattr(settings, "supplier_gmail_refresh_token", "test-placeholder")


def reader_transport(scopes=READONLY_SCOPE, mailbox=MAILBOX, aud="test-client"):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "test-placeholder"} if request.method == "POST" else {"scope": scopes, "aud": aud})
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": mailbox})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "abc123"}], "nextPageToken": "next"})
        if "/attachments/" in request.url.path:
            return httpx.Response(200, json={"data": base64.urlsafe_b64encode(b"test").decode()})
        return httpx.Response(200, json={"id": "abc123", "payload": {}})
    return SupplierGmailReader(httpx.Client(transport=httpx.MockTransport(handler))), requests


def test_only_readonly_methods_and_fixed_mailbox(oauth, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    reader, requests = reader_transport()
    reader.authorize()
    assert reader.list_messages(date(2026, 10, 1), date(2026, 10, 2))["nextPageToken"] == "next"
    reader.message("abc123")
    assert reader.attachment("abc123", "attachment123") == b"test"
    assert [r.method for r in requests] == ["POST", "GET", "GET", "GET", "GET", "GET"]
    assert all(r.method == "GET" and "/users/me/" in r.url.path for r in requests if r.url.host == "gmail.googleapis.com")
    assert requests[3].url.params["maxResults"] == "10"
    assert "after:1790801999" in requests[3].url.params["q"]
    assert "(from:info@inde.gr MEGAPAP)" in requests[3].url.params["q"]
    assert "test-placeholder" not in caplog.text
    with pytest.raises(GmailReadError, match="not allowed"):
        reader._get("messages/abc123/modify")
    reader.close()


@pytest.mark.parametrize("scope", ["https://mail.google.com/", READONLY_SCOPE + " https://www.googleapis.com/auth/gmail.modify", READONLY_SCOPE + " https://www.googleapis.com/auth/drive"])
def test_broader_credentials_rejected_before_mailbox_read(oauth, scope):
    reader, requests = reader_transport(scopes=scope)
    with pytest.raises(GmailReadError, match="broader permissions"):
        reader.authorize()
    assert len(requests) == 2
    assert reader.token is None
    reader.close()


def test_wrong_account_and_wrong_client_are_rejected(oauth):
    for kwargs, count in [({"mailbox": "not-the-configured-mailbox"}, 3), ({"aud": "wrong-client"}, 2)]:
        reader, requests = reader_transport(**kwargs)
        with pytest.raises(GmailReadError):
            reader.authorize()
        assert len(requests) == count
        assert reader.token is None
        reader.close()


def test_errors_never_expose_credentials_and_cooldown_is_bounded():
    for status in [400, 429]:
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"secret": "DO-NOT-EXPOSE"}, headers={"Retry-After": "300"})))
        reader = SupplierGmailReader(client)
        with pytest.raises(GmailReadError) as error:
            reader._json("GET", "https://oauth2.googleapis.com/tokeninfo")
        assert "DO-NOT-EXPOSE" not in str(error.value)
        reader.close()
    with pytest.raises(GmailReadError):
        decode_body("invalid!")


def test_megapap_real_field_structure_and_conservative_doc_type():
    document = MegapapParser().parse(HTML.decode(), filename="Invoice-TEST.pdf").documents[0]
    assert document.document_type == "supplier_order"
    assert document.document_date == date(2026, 10, 2)
    assert document.lines[0].supplier_code == "0212605"
    assert document.lines[0].supplier_sku == "GP041-0025,4"
    assert document.lines[0].quantity == 1
    assert document.lines[0].unit_price_before_discount == D("8.73")
    assert document.lines[0].vat_amount == D("2.10")
    assert document.lines[1].raw_metadata["tax_basis_unconfirmed"] is True
    assert document.gross_total == D("15.73")


def test_pdf_and_html_are_equivalent_and_semantic_duplicates(db):
    pdf = (Path(__file__).parent / "fixtures/megapap_order.pdf").read_bytes()
    parsed = MegapapParser().parse(pdf).documents[0]
    assert parsed.model_dump() == MegapapParser().parse(HTML.decode()).documents[0].model_dump()
    original = stage_source(db, message_id="pdfsource", part_id="1", content=pdf, filename="Invoice-TEST.pdf")
    forwarded = stage(db)
    assert forwarded.status == "duplicate" and forwarded.duplicate_of_id == original.id
    assert count(db, SupplierDocument) == 0


def test_gmail_api_requires_admin_and_invalid_credentials_fail_closed(db, monkeypatch):
    from test_supplier_api import client
    monkeypatch.setattr(settings, "supplier_gmail_enabled", False)
    with client(db, True) as http:
        assert http.get("/api/suppliers/gmail").json()["data"]["configured"] is False
        assert http.get("/api/suppliers/gmail?offset=-1").status_code == 422
        assert http.post("/api/suppliers/gmail/sync", json={"date_from": "2026-10-01", "date_to": "2026-10-02"}).status_code == 503
        assert http.post("/api/suppliers/gmail/sync", json={"date_from": "2026-10-02", "date_to": "2026-10-01"}).status_code == 422
    with client(db, False) as http:
        assert http.get("/api/suppliers/gmail").status_code == 403
        assert http.post("/api/suppliers/gmail/sync", json={"date_from": "2026-10-01", "date_to": "2026-10-02"}).status_code == 403
        assert http.put("/api/suppliers/gmail/00000000-0000-0000-0000-000000000001/review", json={"action": "reject"}).status_code == 403


@pytest.mark.parametrize("value", ["1.2.3", "1.234", "NaN", "-1", "USD 8.73"])
def test_ambiguous_amounts_never_become_zero(value):
    from app.supplier_parsers.megapap import _amount
    with pytest.raises(ValueError):
        _amount(value)


@pytest.mark.parametrize("change", [lambda s: s.replace("8,73", "9,00", 1), lambda s: s.replace("4,90", "5,90"), lambda s: s.replace("SKU", "Unknown"), lambda s: s.replace("MEGAPAP", "Unknown"), lambda s: s.replace("2,10", "3,28")])
def test_parser_rejects_partial_ambiguous_or_changed_layouts(change):
    with pytest.raises(ValueError):
        MegapapParser().parse(change(HTML.decode()))


def admin(db):
    user = User(email=MAILBOX, hashed_password="test-placeholder", is_admin=True)
    db.add(user)
    db.flush()
    return user


def stage(db, message="abc123", content=HTML, filename="order.html"):
    return stage_source(db, message_id=message, part_id="1", content=content, filename=filename, html=True)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def approval(**kwargs):
    return SupplierGmailReviewRequest(action="approve", confirm_supplier_order=True, shipping_net=D("4.90"), shipping_vat=0, **kwargs)


def test_gmail_stage_approve_dedup_financial_atomicity(db):
    from test_supplier_integration import seed
    seed(db)
    user = admin(db)
    row = stage(db)
    assert row.status == "pending"
    assert count(db, SupplierDocument) == count(db, SupplierProductCost) == 0
    assert stage(db).id == row.id
    duplicate = stage(db, "forwarded456", filename="renamed.html")
    assert duplicate.status == "duplicate" and duplicate.duplicate_of_id == row.id
    equivalent = stage(db, "resend789", content=HTML.replace(b"<h1>", b"<h1 class='different'>"))
    assert equivalent.status == "duplicate" and equivalent.duplicate_of_id == row.id
    assert review_gmail_source(db, row.id, approval(), user)["matched_lines"] == 1
    assert count(db, SupplierDocument) == count(db, SupplierProductCost) == count(db, SupplierShippingCost) == 1
    assert db.scalar(select(SupplierProductCost)).net_unit_cost == D("8.73")
    assert db.scalar(select(SupplierShippingCost)).net_shipping_cost == D("4.90")
    assert review_gmail_source(db, row.id, approval(), user)["duplicate"]
    assert count(db, SupplierDocument) == 1
    assert db.get(SupplierGmailSource, row.id).import_batch_id is not None


def test_review_reject_and_confirmation_do_not_create_finance(db):
    user = admin(db)
    row = stage(db)
    with pytest.raises(ValueError, match="Explicitly confirm"):
        review_gmail_source(db, row.id, SupplierGmailReviewRequest(action="approve"), user)
    with pytest.raises(ValueError, match="freight"):
        review_gmail_source(db, row.id, SupplierGmailReviewRequest(action="approve", confirm_supplier_order=True, shipping_net=5, shipping_vat=0), user)
    assert count(db, SupplierDocument) == 0
    review_gmail_source(db, row.id, SupplierGmailReviewRequest(action="reject"), user)
    assert row.status == "rejected" and row.reviewed_by == user.id
    assert count(db, SupplierProductCost) == 0


def test_free_freight_preserves_source_but_imports_zero_shipping(db):
    from test_supplier_integration import seed
    seed(db)
    user = admin(db)
    row = stage(db)
    original = row.normalized_payload
    request = SupplierGmailReviewRequest(action="approve", confirm_supplier_order=True, shipping_waived=True)
    assert review_gmail_source(db, row.id, request, user)["matched_lines"] == 1
    document = db.scalar(select(SupplierDocument))
    shipping = db.scalar(select(SupplierShippingCost))
    assert document.net_products_total == D("8.73")
    assert document.net_shipping_total == shipping.net_shipping_cost == 0
    assert shipping.vat == shipping.gross_shipping_cost == 0
    assert document.vat_total == D("2.10")
    assert document.gross_total == D("10.83")
    assert document.raw_metadata["shipping_waived"] is True
    assert D(document.raw_metadata["original_gross_total"]) == D("15.73")
    assert D(document.raw_metadata["displayed_freight"]) == D("4.90")
    assert document.raw_metadata["freight_confirmed_by"] == str(user.id)
    assert document.raw_metadata["freight_confirmed_at"]
    assert "review_required" not in document.raw_metadata
    assert shipping.raw_metadata["shipping_waived"] is True
    assert row.normalized_payload == original
    assert D(row.normalized_payload["documents"][0]["gross_total"]) == D("15.73")
    assert db.scalar(select(SupplierProductCost)).net_unit_cost == D("8.73")
    assert review_gmail_source(db, row.id, request, user)["duplicate"] is True
    assert count(db, SupplierDocument) == 1
    forwarded = stage(db, message="free-shipping-forward")
    assert forwarded.status == "duplicate" and forwarded.duplicate_of_id == row.id


def test_zero_freight_needs_explicit_waiver_and_order_confirmation(db):
    user = admin(db)
    row = stage(db)
    with pytest.raises(ValueError, match="freight"):
        review_gmail_source(db, row.id, SupplierGmailReviewRequest(
            action="approve", confirm_supplier_order=True, shipping_net=0, shipping_vat=0), user)
    with pytest.raises(ValueError, match="Explicitly confirm"):
        review_gmail_source(db, row.id, SupplierGmailReviewRequest(action="approve", shipping_waived=True), user)
    assert count(db, SupplierDocument) == count(db, SupplierShippingCost) == 0
    assert row.status == "pending"


@pytest.mark.parametrize("values", [{"shipping_net": 1}, {"shipping_vat": 1}])
def test_free_freight_cannot_include_nonzero_cost(values):
    with pytest.raises(ValueError, match="Waived freight"):
        SupplierGmailReviewRequest(action="approve", shipping_waived=True, **values)


def test_confirmed_freight_vat_reconciles_with_document_total(db):
    user = admin(db)
    row = stage(db)
    review_gmail_source(db, row.id, SupplierGmailReviewRequest(
        action="approve", confirm_supplier_order=True, shipping_net=D("3.95"), shipping_vat=D("0.95")), user)
    document = db.scalar(select(SupplierDocument))
    shipping = db.scalar(select(SupplierShippingCost))
    assert document.net_shipping_total == shipping.net_shipping_cost == D("3.95")
    assert shipping.vat == D("0.95")
    assert document.vat_total == D("3.05")
    assert document.gross_total == D("15.73")
    assert document.raw_metadata["shipping_waived"] is False


def test_no_numeric_or_name_auto_match_and_verified_mapping_is_reused(db):
    from test_supplier_integration import seed
    product = seed(db)
    product.model = "DIFFERENT-MODEL"
    product.sku = "0212605"
    db.flush()
    user = admin(db)
    row = stage(db)
    assert review_gmail_source(db, row.id, approval(), user)["unmatched_lines"] == 1
    assert count(db, SupplierProductCost) == 0
    review = unmatched_products(db)[0]
    assert review["supplier_code"] == "0212605" and review["reason"]
    assert review["documents"][0]["purchase_cost"] == 8.73
    mapping = db.scalar(select(SupplierProductMap))
    verify_supplier_mapping(db, mapping.id, VerifySupplierMappingRequest(product_catalog_id=product.id), user)
    assert count(db, SupplierProductCost) == 1
    another = stage(db, "neworder", content=HTML.replace(b"TEST-ORDER-1", b"TEST-ORDER-2"))
    assert review_gmail_source(db, another.id, approval(), user)["matched_lines"] == 1
    assert count(db, SupplierProductCost) == 2


def test_changed_financial_document_is_reviewed_not_double_written(db):
    from test_supplier_integration import seed
    seed(db)
    user = admin(db)
    first = stage(db)
    review_gmail_source(db, first.id, approval(), user)
    changed = stage(db, "changed", content=HTML.replace(b"8,73", b"8,74").replace(b"15,73", b"15,74"))
    assert changed.status == "pending"
    with pytest.raises(ValueError, match="different content"):
        review_gmail_source(db, changed.id, approval(), user)
    assert count(db, SupplierDocument) == count(db, SupplierProductCost) == 1
    assert changed.status == "pending"


def test_unsupported_attachment_stays_in_review(db):
    user = admin(db)
    row = stage_source(db, message_id="unsupported", part_id="2", content=b"not a pdf", filename="invoice.pdf")
    assert row.status == "review" and not row.normalized_payload
    with pytest.raises(ValueError, match="Unsupported"):
        review_gmail_source(db, row.id, approval(), user)
    assert count(db, SupplierDocument) == 0


def test_sync_uses_immutable_ids_and_no_financial_write(db, monkeypatch):
    class FakeReader:
        def authorize(self): pass
        def close(self): pass
        def list_messages(self, *args): return {"messages": [{"id": "abc123"}], "nextPageToken": "next"}
        def message(self, *args): return {"payload": {"headers": [{"name": "From", "value": MAILBOX}], "mimeType": "text/html", "partId": "0", "body": {"data": base64.urlsafe_b64encode(HTML).decode()}}}
    monkeypatch.setattr("app.services.supplier_gmail_service.SupplierGmailReader", FakeReader)
    request = SupplierGmailSyncRequest(date_from=date(2026, 10, 1), date_to=date(2026, 10, 2))
    assert sync_supplier_gmail(db, request)["pending"] == 1
    assert sync_supplier_gmail(db, request)["existing"] == 1
    assert count(db, SupplierGmailSource) == 1
    assert count(db, SupplierDocument) == 0


def test_concurrent_gmail_receipts_and_approval_commit_once(db):
    engine = create_engine(os.environ["SUPPLIER_TEST_DATABASE_URL"])
    nonce = uuid4().hex
    source = HTML.replace(b"TEST-ORDER-1", nonce.encode())
    user_id = product_id = supplier_id = None
    try:
        with Session(engine) as session:
            assert session.scalar(select(Supplier.id).where(Supplier.code == "MEGAPAP")) is None
            user = admin(session)
            product = ProductCatalog(product_id=nonce, sku=nonce, model="GP041-0025,4", name="Concurrency fixture")
            session.add(product)
            session.commit()
            user_id, product_id = user.id, product.id
        def receive(index):
            with Session(engine, autoflush=False) as session:
                row = stage_source(session, message_id=nonce + str(index), part_id="1", content=source, html=True)
                session.commit()
                return row.id, row.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(receive, range(2)))
        assert sorted(status for _, status in receipts) == ["duplicate", "pending"]
        source_id = next(identifier for identifier, status in receipts if status == "pending")
        def accept(_):
            with Session(engine, autoflush=False) as session:
                return review_gmail_source(session, source_id, approval(), session.get(User, user_id))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(accept, range(2)))
        assert sum(result["documents_imported"] for result in results) == 1
        assert sum(result["duplicate"] for result in results) == 1
        with Session(engine) as session:
            supplier_id = session.scalar(select(Supplier.id).where(Supplier.code == "MEGAPAP"))
            assert session.scalar(select(func.count()).select_from(SupplierDocument).where(SupplierDocument.supplier_id == supplier_id)) == 1
            assert session.scalar(select(func.count()).select_from(SupplierProductCost).where(SupplierProductCost.supplier_id == supplier_id)) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(delete(SupplierGmailSource).where(SupplierGmailSource.message_id.like(nonce + "%")))
            supplier_id = supplier_id or connection.scalar(select(Supplier.id).where(Supplier.code == "MEGAPAP"))
            if supplier_id:
                for model in (SupplierProductCost, SupplierShippingCost, SupplierDocument, SupplierImportBatch, SupplierProductMap):
                    connection.execute(delete(model).where(model.supplier_id == supplier_id))
                connection.execute(delete(Supplier).where(Supplier.id == supplier_id))
            if product_id:
                connection.execute(delete(ProductCatalog).where(ProductCatalog.id == product_id))
            if user_id:
                connection.execute(delete(User).where(User.id == user_id))
        engine.dispose()
