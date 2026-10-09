"""Reconcile provider UBL product identifiers/quantities with its fiscal XML."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.connectors.aade_detail import DetailError, MAX_BYTES, _amount

NS = {"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
      "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"}
VERSION = 1


def supplement_invoice(invoice, data):
    if len(data) > MAX_BYTES:
        raise DetailError("Provider UBL exceeded the size limit.")
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except (ParseError, DefusedXmlException):
        raise DetailError("Provider UBL is not safe invoice XML.") from None
    if root.tag != "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice" or len(list(root.iter())) > 20000:
        raise DetailError("Provider UBL is not a single supported invoice.")

    def text(node, path):
        found = node.findall(path, NS)
        if len(found) != 1 or not (found[0].text or "").strip():
            raise DetailError("Provider UBL has missing or ambiguous fields.")
        return found[0].text.strip()

    def amount(node, path):
        value = _amount(text(node, path))
        element = node.find(path, NS)
        if element.get("currencyID") != "EUR":
            raise DetailError("Provider UBL currency does not match the fiscal invoice.")
        return value

    def same(actual, expected):
        if str(actual).strip() != str(expected).strip():
            raise DetailError("Provider UBL invoice identity does not match myDATA.")

    header, summary = invoice.get("invoiceHeader") or {}, invoice.get("invoiceSummary") or {}
    issuer, recipient = invoice.get("issuer") or {}, invoice.get("counterpart") or {}
    same(text(root, "cbc:IssueDate"), header.get("issueDate"))
    same(text(root, "cbc:DocumentCurrencyCode"), header.get("currency") or "EUR")
    for party, vat in (("AccountingSupplierParty", issuer.get("vatNumber")), ("AccountingCustomerParty", recipient.get("vatNumber"))):
        same(text(root, f"cac:{party}/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"), "EL" + str(vat))
    # This provider's ID includes issuer, date, branch, myDATA type, series and AA.
    parts = text(root, "cbc:ID").split("|")
    if len(parts) != 6:
        raise DetailError("Provider UBL invoice number is not supported.")
    for actual, expected in zip((parts[0], parts[1], parts[3], parts[4], parts[5]),
                                (issuer.get("vatNumber"), date.fromisoformat(header["issueDate"]).strftime("%d/%m/%Y"),
                                 header.get("invoiceType"), header.get("series"), header.get("aa"))):
        same(actual, expected)
    marks = [text(ref, "cbc:ID") for ref in root.findall("cac:AdditionalDocumentReference", NS)
             if ref.findtext("cbc:DocumentDescription", namespaces=NS) == "##M.AR.K##"]
    if len(marks) != 1:
        raise DetailError("Provider UBL has no unique AADE MARK.")
    same(marks[0], invoice.get("mark"))
    for path, key in (("cac:LegalMonetaryTotal/cbc:LineExtensionAmount", "totalNetValue"),
                      ("cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount", "totalNetValue"),
                      ("cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount", "totalGrossValue"),
                      ("cac:TaxTotal/cbc:TaxAmount", "totalVatAmount")):
        if abs(amount(root, path) - _amount(summary.get(key))) > Decimal("0.02"):
            raise DetailError("Provider UBL totals do not reconcile to myDATA.")
    fiscal = invoice.get("invoiceDetails") or []
    fiscal = fiscal if isinstance(fiscal, list) else [fiscal]
    lines = root.findall("cac:InvoiceLine", NS)
    if not lines or len(lines) != len(fiscal) or len(lines) > 1000:
        raise DetailError("Provider UBL line count differs from myDATA.")
    indexed = {text(line, "cbc:ID"): line for line in lines}
    if len(indexed) != len(lines) or set(indexed) != {str(line.get("lineNumber")) for line in fiscal}:
        raise DetailError("Provider UBL line numbers differ from myDATA.")
    result = deepcopy(invoice)
    merged = []
    for source in fiscal:
        line = indexed[str(source["lineNumber"])]
        same(" ".join(text(line, "cac:Item/cbc:Name").split()), " ".join(str(source.get("itemDescr") or "").split()))
        net = amount(line, "cbc:LineExtensionAmount")
        if abs(net - _amount(source.get("netValue"))) > Decimal("0.02"):
            raise DetailError("Provider UBL line value differs from myDATA.")
        quantity = _amount(text(line, "cbc:InvoicedQuantity"))
        base = _amount(text(line, "cac:Price/cbc:BaseQuantity"))
        if quantity <= 0 or base <= 0 or line.findall("cac:AllowanceCharge", NS):
            raise DetailError("Provider UBL quantity or line allowances require review.")
        price = amount(line, "cac:Price/cbc:PriceAmount")
        if abs(price * quantity / base - net) > Decimal("0.02"):
            raise DetailError("Provider UBL quantity and price do not reconcile.")
        rate = _amount(text(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"))
        if abs(net * rate / 100 - _amount(source.get("vatAmount"))) > Decimal("0.02"):
            raise DetailError("Provider UBL line VAT differs from myDATA.")
        code = text(line, "cac:Item/cac:SellersItemIdentification/cbc:ID")
        if source.get("itemCode"):
            same(code, source["itemCode"])
        unit = line.find("cbc:InvoicedQuantity", NS).get("unitCode")
        # Gloria's UBL uses E48 even for pieces (confirmed against its PDF).
        # Never interpret E48 as pieces for other suppliers or override myDATA units.
        pieces = unit in {"C62", "H87"} or (unit == "E48" and issuer.get("vatNumber") == "094494879")
        if not pieces or str(source.get("measurementUnit")) != "1":
            raise DetailError("Provider UBL purchase unit requires confirmation.")
        merged.append({**source, "itemCode": code, "quantity": str(quantity),
                       "_ubl_evidence": {"version": VERSION, "original_quantity": source.get("quantity"), "unit_code": unit}})
    result["invoiceDetails"] = merged
    return result
