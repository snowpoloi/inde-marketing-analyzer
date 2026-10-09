from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.connectors import aade_detail as detail
from app.models import SupplierProductCost, IntegrationSetting
from app.services import aade_detail_jobs as jobs
from app.services.dashboard_service import _aade_line_items
from app.services.import_service import import_aade_payload
from app.services.supplier_aade_costs import invoice_preview, line_rows
from test_supplier_aade_costs import auto_policy, seed


URL = "https://e-invoicing.gr/invoice/private?key=private"


def invoice():
    return {"mark": "400015407466619", "uid": "test-uid", "issuer": {"vatNumber": "800749270"},
            "counterpart": {"vatNumber": "802216736"},
            "invoiceHeader": {"issueDate": "2026-09-25", "invoiceType": "1.1", "series": "ΤΔΑ11", "aa": "100647", "currency": "EUR"},
            "invoiceSummary": {"totalNetValue": "114.32", "totalVatAmount": "27.44", "totalGrossValue": "141.76"},
            "invoiceDetails": [{"lineNumber": "1", "itemCode": "123-000005", "itemDescr": "SANTE", "quantity": "1.00", "netValue": "54.96", "vatAmount": "13.19"},
                               {"lineNumber": "2", "itemCode": "072-000075", "itemDescr": "Soco", "quantity": "1.00", "netValue": "59.36", "vatAmount": "14.25"}]}


def document():
    return SimpleNamespace(mark="400015407466619", uid="test-uid", issuer_vat="800749270", counterpart_vat="802216736",
                           issue_date=date(2026, 9, 25), invoice_type="1.1", series="ΤΔΑ11", aa="100647", currency="EUR",
                           net_value=Decimal("114.32"), vat_amount=Decimal("27.44"), gross_value=Decimal("141.76"))


def xml():
    def node(key, value):
        if isinstance(value, list):
            return "".join(node(key, row) for row in value)
        return f"<{key}>" + ("".join(node(k, v) for k, v in value.items()) if isinstance(value, dict) else str(value)) + f"</{key}>"
    return ('<InvoicesDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">' + node("invoice", invoice()) + '</InvoicesDoc>').encode()


def test_real_pakketo_shape_preserves_missing_unit():
    parsed = detail.validate_invoice(document(), detail.parse_detail(xml()))
    assert parsed["invoiceDetails"][0]["itemCode"] == "123-000005"
    assert "measurementUnit" not in parsed["invoiceDetails"][0]
    from app.services.supplier_aade_costs import parse_lines
    assert parse_lines(parsed)[0]["unit_cost_net"] is None
    assert "pieces" in parse_lines(parsed)[0]["reasons"][0]


@pytest.mark.parametrize("url", ["http://e-invoicing.gr/a", "https://127.0.0.1/a", "https://evil.example/a",
    "https://e-invoicing.gr.evil.example/a", "https://user:password@e-invoicing.gr/a", "https://e-invoicing.gr:8443/a", "https://e-invoicing.gr/a#token"])
def test_unsafe_urls_blocked(url):
    with pytest.raises(detail.DetailError):
        detail.detail_url(url)


def test_download_suffix_and_query():
    assert detail.detail_url(URL + "&format=1") == "https://e-invoicing.gr/invoice/private/myDATA?key=private&format=1"
    assert detail.detail_url("https://einvoice.impact.gr/a/pdf?q=1") == "https://einvoice.impact.gr/a/myDATA?q=1"


@pytest.mark.parametrize("patch", [lambda i: i.update(mark="other"), lambda i: i["issuer"].update(vatNumber="other"),
    lambda i: i["counterpart"].update(vatNumber="other"), lambda i: i["invoiceHeader"].update(aa="other"),
    lambda i: i["invoiceHeader"].update(issueDate="2026-09-26"), lambda i: i["invoiceHeader"].update(invoiceType="5.1"),
    lambda i: i["invoiceSummary"].update(totalNetValue="115"), lambda i: i["invoiceDetails"][0].update(netValue="55"),
    lambda i: i["invoiceDetails"][0].update(vatAmount=None), lambda i: i["invoiceDetails"][0].update(netValue="NaN"),
    lambda i: i["invoiceDetails"][1].update(lineNumber="1")])
def test_wrong_invoice_is_never_used(patch):
    payload = invoice(); patch(payload)
    with pytest.raises(detail.DetailError):
        detail.validate_invoice(document(), payload)


@pytest.mark.parametrize("data", [b'<html>login</html>', b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>',
    b'<InvoicesDoc><invoice><mark>1</mark></invoice><invoice><mark>2</mark></invoice></InvoicesDoc>', b'x' * (detail.MAX_BYTES + 1)],
    ids=["html", "xxe", "multiple-invoices", "oversized"])
def test_untrusted_xml_blocked(data):
    with pytest.raises(detail.DetailError):
        detail.parse_detail(data)


@pytest.mark.parametrize("data", [b'<html>temporarily unavailable</html>', b'<InvoicesDoc', b''])
def test_transient_invalid_responses_are_retryable(data):
    with pytest.raises(detail.DetailError) as error:
        detail.parse_detail(data)
    assert error.value.retryable


def test_unsafe_xml_is_not_retryable():
    with pytest.raises(detail.DetailError) as error:
        detail.parse_detail(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    assert not error.value.retryable


def test_get_without_credentials_and_no_unsafe_redirect(monkeypatch):
    real_client = httpx.Client
    requests = []
    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert not any(k in request.headers for k in ("Authorization", "aade-user-id", "Ocp-Apim-Subscription-Key"))
        return httpx.Response(200, content=xml())
    monkeypatch.setattr(detail, "_public_host", lambda host: None)
    monkeypatch.setattr(detail.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    assert detail.fetch_detail(URL)["mark"] == document().mark
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/myDATA")
    monkeypatch.setattr(detail.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"Location": "https://evil.example/"})), **kw))
    with pytest.raises(detail.DetailError, match="origin|unsafe"):
        detail.fetch_detail(URL)


def test_private_dns_blocked(monkeypatch):
    monkeypatch.setattr(detail.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(detail.DetailError, match="non-public"):
        detail.fetch_detail(URL)


def verified_raw(original, payload):
    return {**original, detail.META_KEY: {"status": "verified", "source_hash": detail.source_fingerprint(original), "invoice": payload}}


def test_render_and_invalidation():
    raw = {"downloadingInvoiceUrl": URL, "invoiceDetails": {"quantity": "2", "netValue": "114.32", "vatAmount": "27.44"}}
    enriched = verified_raw(raw, invoice())
    lines = _aade_line_items(enriched)
    assert len(lines) == 2 and lines[0]["unit_price"] == 54.96
    assert lines[0]["source"] == "Provider via AADE"
    assert len(line_rows({**enriched, "mark": "changed"})) == 1
    assert detail.detail_info({**enriched, "mark": "changed"})["status"] == "pending"


def test_cost_bookkeeping_preserves_verified_products_and_costs():
    raw = {"downloadingInvoiceUrl": URL, "invoiceDetails": {"quantity": "2", "netValue": "114.32", "vatAmount": "27.44"}}
    enriched = verified_raw(raw, invoice())
    for status in ("review", "imported"):
        enriched = {**enriched, "_catalog_cost": {"status": status, "checked_at": "2026-10-10"}}
        assert detail.detail_info(enriched)["status"] == "verified"
        assert detail.effective_invoice(enriched) == invoice()
        assert len(_aade_line_items(enriched)) == 2
        assert line_rows(enriched) == invoice()["invoiceDetails"]
    assert detail.source_fingerprint(enriched) == detail.source_fingerprint(raw)


def test_legacy_fingerprint_with_cost_bookkeeping_is_still_usable():
    raw = {"downloadingInvoiceUrl": URL, "_catalog_cost": {"status": "review"}}
    legacy_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    enriched = {**raw, detail.META_KEY: {"status": "verified", "source_hash": legacy_hash, "invoice": invoice()}}
    assert legacy_hash != detail.source_fingerprint(raw)
    assert detail.detail_info(enriched)["status"] == "verified"
    assert len(line_rows(enriched)) == 2
    assert detail.detail_info({**enriched, "mark": "changed"})["status"] == "pending"


@pytest.mark.parametrize("field,value", [
    ("mark", "changed"), ("downloadingInvoiceUrl", URL + "changed"),
    ("invoiceDetails", [{"lineNumber": "1", "netValue": "999"}]),
    ("issuer", {"vatNumber": "other"}), ("invoiceSummary", {"totalNetValue": "999"}),
    ("_unknown_metadata", {"untrusted": True}),
])
def test_cost_bookkeeping_does_not_hide_source_changes(field, value):
    raw = {"mark": document().mark, "downloadingInvoiceUrl": URL,
           "invoiceDetails": {"netValue": "114.32", "vatAmount": "27.44"}}
    enriched = {**verified_raw(raw, invoice()), "_catalog_cost": {"status": "review"}, field: value}
    assert detail.detail_info(enriched)["status"] == "pending"
    assert detail.effective_invoice(enriched) is enriched


def configure_fiscal(db):
    _, supplier, _, _, fiscal = seed(db)
    db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "aade")).is_enabled = True
    fiscal.raw = {**fiscal.raw, "downloadingInvoiceUrl": URL}
    db.commit()
    payload = {"mark": fiscal.mark, "issuer": {"vatNumber": fiscal.issuer_vat}, "counterpart": {"vatNumber": fiscal.counterpart_vat},
               "invoiceHeader": {"issueDate": str(fiscal.issue_date), "invoiceType": fiscal.invoice_type,
                                 "series": fiscal.series, "aa": fiscal.aa, "currency": fiscal.currency},
               "invoiceSummary": {"totalNetValue": str(fiscal.net_value), "totalVatAmount": str(fiscal.vat_amount), "totalGrossValue": str(fiscal.gross_value)},
               "invoiceDetails": deepcopy(fiscal.raw["invoiceDetails"])}
    return supplier, fiscal, payload


def test_worker_no_financial_acceptance_and_resync(db, monkeypatch):
    supplier, fiscal, payload = configure_fiscal(db)
    original = deepcopy(fiscal.raw)
    monkeypatch.setattr(jobs, "fetch_detail", lambda url: payload)
    assert jobs.process_aade_details(db) == {"processed": 1, "verified": 1}
    db.refresh(fiscal)
    assert fiscal.raw[detail.META_KEY]["status"] == "verified"
    assert {k:v for k,v in fiscal.raw.items() if k != detail.META_KEY} == original
    assert invoice_preview(db, fiscal.id, supplier.id)["can_import"]
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    assert jobs.process_aade_details(db)["processed"] == 0
    row = {key: getattr(fiscal, key) for key in ("source_endpoint", "identity_key", "mark", "uid", "issuer_vat", "counterpart_vat",
           "issue_date", "invoice_type", "document_direction", "series", "aa", "currency", "net_value", "vat_amount", "gross_value", "is_cancelled", "cancelled_by_mark")}
    row["raw"] = original
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "verified"
    row["raw"] = {**original, "downloadingInvoiceUrl": URL + "changed"}
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert detail.META_KEY not in fiscal.raw


def test_cost_bookkeeping_during_download_and_resync(db, monkeypatch):
    supplier, fiscal, payload = configure_fiscal(db)
    original = deepcopy(fiscal.raw)

    def download(url):
        fiscal.raw = {**fiscal.raw, "_catalog_cost": {"status": "review"}}
        db.commit()
        return payload

    monkeypatch.setattr(jobs, "fetch_detail", download)
    assert jobs.process_aade_details(db) == {"processed": 1, "verified": 1}
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "verified"
    assert invoice_preview(db, fiscal.id, supplier.id)["can_import"]
    row = {key: getattr(fiscal, key) for key in ("source_endpoint", "identity_key", "mark", "uid", "issuer_vat", "counterpart_vat",
           "issue_date", "invoice_type", "document_direction", "series", "aa", "currency", "net_value", "vat_amount", "gross_value", "is_cancelled", "cancelled_by_mark")}
    row["raw"] = original
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "verified"
    assert invoice_preview(db, fiscal.id, supplier.id)["can_import"]
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("blocked", [False, True])
def test_cost_worker_keeps_verified_details_and_cost_provenance(db, legacy, blocked):
    from app.services.supplier_aade_jobs import process_aade_costs
    from app.services.supplier_catalog_pricing import latest_aade_costs

    user, supplier, product, item, fiscal = seed(db)
    raw = {**fiscal.raw, "downloadingInvoiceUrl": URL, "_catalog_cost": {}}
    enriched = verified_raw(raw, {"invoiceDetails": deepcopy(raw["invoiceDetails"])})
    if legacy:
        enriched[detail.META_KEY]["source_hash"] = hashlib.sha256(
            json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    fiscal.raw = enriched
    if blocked:
        item.product_catalog_id = None
    db.commit()
    auto_policy(db, user, supplier)
    result = process_aade_costs(db)
    db.refresh(fiscal)
    assert result["status"] == ("review" if blocked else "imported")
    assert detail.detail_info(fiscal.raw)["status"] == "verified"
    assert fiscal.raw[detail.META_KEY]["source_hash"] == detail.source_fingerprint(fiscal.raw)
    assert len(line_rows(fiscal.raw)) == 2
    costs = latest_aade_costs(db, {product.id}, {supplier.code})
    if blocked:
        assert costs == {}
    else:
        assert costs[(supplier.code, product.id)][0].net_unit_cost == 70
    assert process_aade_costs(db) == {"processed": 0}


def test_worker_retry_lease_and_rejection(db, monkeypatch):
    _, fiscal, _ = configure_fiscal(db)
    def fail(url):
        raise detail.DetailError("Provider temporarily unavailable.", retryable=True)
    monkeypatch.setattr(jobs, "fetch_detail", fail)
    assert jobs.process_aade_details(db)["processed"] == 1
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "retry"
    assert jobs.process_aade_details(db)["processed"] == 0
    fiscal.raw = {**fiscal.raw, detail.META_KEY: {**fiscal.raw[detail.META_KEY], "status": "running",
        "next_attempt_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}}
    db.commit()
    monkeypatch.setattr(jobs, "fetch_detail", lambda url: invoice())
    assert jobs.process_aade_details(db) == {"processed": 1, "verified": 0}
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "unavailable"
    assert "identity" in fiscal.raw[detail.META_KEY]["reason"]


def test_worker_cancellation_during_download(db, monkeypatch):
    _, fiscal, payload = configure_fiscal(db)
    def download(url):
        fiscal.is_cancelled = True
        db.commit()
        return payload
    monkeypatch.setattr(jobs, "fetch_detail", download)
    jobs.process_aade_details(db)
    db.refresh(fiscal)
    assert fiscal.raw[detail.META_KEY]["status"] != "verified"


def test_disabled_integration_never_downloads(db, monkeypatch):
    configure_fiscal(db)
    db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "aade")).is_enabled = False
    db.commit()
    monkeypatch.setattr(jobs, "fetch_detail", lambda url: pytest.fail("Disabled AADE made a provider request"))
    assert jobs.process_aade_details(db) == {"processed": 0}


def test_source_change_during_download_discards_result(db, monkeypatch):
    _, fiscal, payload = configure_fiscal(db)
    def changed(url):
        fiscal.raw = {"downloadingInvoiceUrl": URL + "new", "invoiceDetails": []}
        db.commit()
        return payload
    monkeypatch.setattr(jobs, "fetch_detail", changed)
    jobs.process_aade_details(db)
    db.refresh(fiscal)
    assert detail.META_KEY not in fiscal.raw


def test_verified_invoiceportal_details_upgrade_once_without_financial_acceptance(db, monkeypatch):
    _, fiscal, payload = configure_fiscal(db)
    fiscal.issuer_vat = "094494879"
    payload["issuer"]["vatNumber"] = fiscal.issuer_vat
    raw = {**fiscal.raw, "downloadingInvoiceUrl": "https://invoiceportal.gr/invoices/private/pdf",
           "_catalog_cost": {"status": "review", "next_attempt_at": "2099-01-01"}}
    fiscal.raw = verified_raw(raw, payload)
    db.commit()
    monkeypatch.setattr(jobs, "fetch_detail", lambda url: payload)
    assert jobs.process_aade_details(db) == {"processed": 1, "verified": 1}
    db.refresh(fiscal)
    assert fiscal.raw[detail.META_KEY]["ubl_version"] == 1
    assert fiscal.raw["_catalog_cost"]["next_attempt_at"] is None
    assert jobs.process_aade_details(db) == {"processed": 0, "verified": 0}
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_failed_invoiceportal_upgrade_cannot_reuse_old_wrong_quantity(db, monkeypatch):
    _, fiscal, payload = configure_fiscal(db)
    fiscal.issuer_vat = "094494879"
    payload["issuer"]["vatNumber"] = fiscal.issuer_vat
    raw = {**fiscal.raw, "downloadingInvoiceUrl": "https://invoiceportal.gr/invoices/private/pdf"}
    fiscal.raw = verified_raw(raw, payload)
    db.commit()
    def fail(url):
        raise detail.DetailError("UBL quantity does not reconcile.")
    monkeypatch.setattr(jobs, "fetch_detail", fail)
    assert jobs.process_aade_details(db) == {"processed": 1, "verified": 0}
    db.refresh(fiscal)
    assert detail.detail_info(fiscal.raw)["status"] == "unavailable"
    assert detail.effective_invoice(fiscal.raw) == fiscal.raw
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
