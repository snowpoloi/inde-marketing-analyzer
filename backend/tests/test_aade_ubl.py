from copy import deepcopy
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import httpx
import pytest

from app.connectors import aade_detail as detail
from app.connectors.aade_ubl import NS, supplement_invoice
from app.services.supplier_aade_costs import parse_lines


def fiscal():
    return {"mark": "12345", "issuer": {"vatNumber": "094494879"}, "counterpart": {"vatNumber": "802216736"},
            "invoiceHeader": {"issueDate": "2026-10-07", "invoiceType": "1.1", "series": "TH", "aa": "62476", "currency": "EUR"},
            "invoiceSummary": {"totalNetValue": "24.18", "totalVatAmount": "5.80", "totalGrossValue": "29.98"},
            "invoiceDetails": [{"lineNumber": "1", "quantity": "1", "measurementUnit": "1", "itemDescr": "LINDA mirror", "netValue": "24.18", "vatAmount": "5.80"}]}


def ubl():
    return ET.fromstring('''<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
        xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
      <cbc:ID>094494879|07/10/2026|17|1.1|TH|62476</cbc:ID><cbc:IssueDate>2026-10-07</cbc:IssueDate><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
      <cac:AdditionalDocumentReference><cbc:ID>12345</cbc:ID><cbc:DocumentDescription>##M.AR.K##</cbc:DocumentDescription></cac:AdditionalDocumentReference>
      <cac:AccountingSupplierParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>EL094494879</cbc:CompanyID></cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>
      <cac:AccountingCustomerParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>EL802216736</cbc:CompanyID></cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>
      <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">5.80</cbc:TaxAmount></cac:TaxTotal>
      <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">24.18</cbc:LineExtensionAmount><cbc:TaxExclusiveAmount currencyID="EUR">24.18</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">29.98</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>
      <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="E48">2</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">24.18</cbc:LineExtensionAmount>
        <cac:Item><cbc:Name>LINDA mirror</cbc:Name><cac:SellersItemIdentification><cbc:ID>70-6041</cbc:ID></cac:SellersItemIdentification><cac:ClassifiedTaxCategory><cbc:Percent>24.00</cbc:Percent></cac:ClassifiedTaxCategory></cac:Item>
        <cac:Price><cbc:PriceAmount currencyID="EUR">24.18</cbc:PriceAmount><cbc:BaseQuantity>2</cbc:BaseQuantity></cac:Price>
      </cac:InvoiceLine></Invoice>''')


def test_gloria_correct_identifier_quantity_cost_and_audit():
    source = fiscal()
    result = supplement_invoice(source, ET.tostring(ubl()))
    assert source == fiscal()
    line = result["invoiceDetails"][0]
    assert line["itemCode"] == "70-6041" and line["quantity"] == "2"
    assert line["measurementUnit"] == "1"
    assert line["_ubl_evidence"]["original_quantity"] == "1"
    assert parse_lines(result)[0]["unit_cost_net"] == Decimal("12.09")


@pytest.mark.parametrize("path,value", [
    ("cbc:ID", "094494879|07/10/2026|17|1.1|TH|OTHER"), ("cbc:IssueDate", "2026-10-08"),
    ("cbc:DocumentCurrencyCode", "USD"), ("cac:AdditionalDocumentReference/cbc:ID", "OTHER"),
    ("cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", "EL000000000"),
    ("cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", "EL000000000"),
    ("cac:TaxTotal/cbc:TaxAmount", "6.00"), ("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount", "30.00"),
    ("cac:InvoiceLine/cbc:ID", "2"), ("cac:InvoiceLine/cbc:LineExtensionAmount", "30.00"),
    ("cac:InvoiceLine/cbc:InvoicedQuantity", "0"), ("cac:InvoiceLine/cac:Price/cbc:BaseQuantity", "1"),
    ("cac:InvoiceLine/cac:Item/cbc:Name", "Another item"),
    ("cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", "13"),
    ("cac:InvoiceLine/cac:Price/cbc:PriceAmount", "NaN")])
def test_conflicts_fail_closed(path, value):
    root = ubl(); root.find(path, NS).text = value
    with pytest.raises(detail.DetailError):
        supplement_invoice(fiscal(), ET.tostring(root))


@pytest.mark.parametrize("mutation", ["extra_line", "duplicate_mark", "missing_code", "currency", "unknown_unit", "allowance"])
def test_ambiguous_or_unsupported_lines_blocked(mutation):
    root = ubl(); line = root.find("cac:InvoiceLine", NS)
    if mutation == "extra_line": root.append(deepcopy(line))
    elif mutation == "duplicate_mark": root.append(deepcopy(root.find("cac:AdditionalDocumentReference", NS)))
    elif mutation == "missing_code": line.find("cac:Item/cac:SellersItemIdentification", NS).clear()
    elif mutation == "currency": line.find("cbc:LineExtensionAmount", NS).set("currencyID", "USD")
    elif mutation == "unknown_unit": line.find("cbc:InvoicedQuantity", NS).set("unitCode", "KGM")
    else: ET.SubElement(line, "{" + NS["cac"] + "}AllowanceCharge")
    with pytest.raises(detail.DetailError): supplement_invoice(fiscal(), ET.tostring(root))


def test_existing_code_conflict_and_unit_not_overridden():
    for field, value in (("itemCode", "OTHER"), ("measurementUnit", "3")):
        source = fiscal(); source["invoiceDetails"][0][field] = value
        with pytest.raises(detail.DetailError): supplement_invoice(source, ET.tostring(ubl()))
    source = fiscal(); source["issuer"]["vatNumber"] = "123456789"
    root = ubl()
    root.find("cbc:ID", NS).text = root.find("cbc:ID", NS).text.replace("094494879", "123456789")
    root.find("cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", NS).text = "EL123456789"
    with pytest.raises(detail.DetailError, match="unit"): supplement_invoice(source, ET.tostring(root))


@pytest.mark.parametrize("data", [b"<html/>", b"<Invoice", b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>', b"x" * (detail.MAX_BYTES + 1)], ids=["html", "invalid", "xxe", "oversized"])
def test_untrusted_ubl_rejected(data):
    with pytest.raises(detail.DetailError): supplement_invoice(fiscal(), data)


@pytest.mark.parametrize("has_code", [False, True])
def test_provider_fetches_same_origin_ubl_without_credentials(monkeypatch, has_code):
    real_client = httpx.Client; paths = []
    def respond(request):
        paths.append(request.url.path)
        assert request.method == "GET" and request.url.host == "invoiceportal.gr"
        assert not any(key in request.headers for key in ("Authorization", "aade-user-id", "Ocp-Apim-Subscription-Key"))
        return httpx.Response(200, content=ET.tostring(ubl()) if request.url.path.endswith("EN16931") else b"<unused/>")
    monkeypatch.setattr(detail, "_public_host", lambda host: None)
    source = fiscal()
    if has_code:
        source["invoiceDetails"][0]["itemCode"] = "70-6041"
    monkeypatch.setattr(detail, "parse_detail", lambda data: source)
    monkeypatch.setattr(detail.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    assert detail.fetch_detail("https://invoiceportal.gr/invoices/private/pdf")["invoiceDetails"][0]["itemCode"] == "70-6041"
    assert paths == ["/invoices/private/myDATA", "/invoices/private/EN16931"]


def test_verified_gloria_cost_import_and_duplicate_protection(db):
    from sqlalchemy import select
    from app.models import SupplierCatalogFeed, SupplierProductCost
    from app.services.supplier_aade_jobs import process_aade_costs
    from app.services.supplier_catalog_pricing import latest_aade_costs
    from test_supplier_aade_costs import seed, auto_policy

    actor, supplier, product, item, document = seed(db)
    supplier.vat_number = "094494879"
    feed = db.scalar(select(SupplierCatalogFeed).where(SupplierCatalogFeed.code == supplier.code))
    feed.adapter = "gloria"
    product.sku = "GL.70-6041"
    item.supplier_code = item.supplier_sku = "70-6041"
    source = fiscal()
    document.issuer_vat = supplier.vat_number
    document.mark = source["mark"]
    document.issue_date = date(2026, 10, 7)
    document.series = "TH"; document.aa = "62476"
    document.net_value = Decimal("24.18"); document.vat_amount = Decimal("5.80"); document.gross_value = Decimal("29.98")
    raw = {**source, "downloadingInvoiceUrl": "https://invoiceportal.gr/invoices/private/pdf"}
    document.raw = {**raw, detail.META_KEY: {"status": "verified", "source_hash": detail.source_fingerprint(raw),
                                          "invoice": supplement_invoice(source, ET.tostring(ubl()))}}
    db.commit(); auto_policy(db, actor, supplier)
    assert process_aade_costs(db)["costs_created"] == 1
    assert db.scalar(select(SupplierProductCost.net_unit_cost)) == Decimal("12.09")
    costs = latest_aade_costs(db, {product.id}, {supplier.code})
    assert costs[(supplier.code, product.id)][0].net_unit_cost == Decimal("12.09")
    assert process_aade_costs(db) == {"processed": 0}
