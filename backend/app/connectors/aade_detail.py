"""Retrieve provider myDATA detail using only the download link received from AADE."""

import hashlib
import ipaddress
import json
import socket
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.connectors.aade import AADEConnector

META_KEY = "_provider_detail"
MAX_BYTES = 2 * 1024 * 1024
# Exact provider origins observed in the authenticated AADE responses. Never
# accept arbitrary supplier-entered URLs or send AADE credentials to a provider.
PROVIDER_HOSTS = frozenset({
    "e-invoicing.gr", "einvoice.impact.gr", "invoiceportal.gr",
    "onesign-api.onesys.gr", "app.elorusfuse.gr", "srv.parochos.gr",
    "srv2.parochos.gr", "einvoice.s1ecos.gr", "www.eskap.gr",
    "epsilondigital6.epsilonnet.gr", "epsilondigital7.epsilonnet.gr",
    "epsilondigital12.epsilonnet.gr", "epsilondigital27.epsilonnet.gr",
    "epsilondigital-enetgroup.epsilonnet.gr", "epsilondigital-3rd.epsilonnet.gr",
})


class DetailError(ValueError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def source_fingerprint(raw):
    # Local cost-job bookkeeping is not part of the fiscal source document.
    original = {key: value for key, value in raw.items() if key not in {META_KEY, "_catalog_cost"}}
    return hashlib.sha256(json.dumps(original, sort_keys=True, default=str).encode()).hexdigest()


def detail_info(raw):
    meta = raw.get(META_KEY) or {}
    if meta.get("source_hash") != source_fingerprint(raw):
        # Older workers included cost bookkeeping when hashing the source.
        legacy = {key: value for key, value in raw.items() if key != META_KEY}
        legacy_hash = hashlib.sha256(json.dumps(legacy, sort_keys=True, default=str).encode()).hexdigest()
        if meta.get("source_hash") != legacy_hash:
            return {"status": "pending" if raw.get("downloadingInvoiceUrl") else "no_link"}
    return {key: meta.get(key) for key in ("status", "reason", "host", "checked_at")}


def effective_invoice(raw):
    meta = raw.get(META_KEY) or {}
    if detail_info(raw)["status"] == "verified" and isinstance(meta.get("invoice"), dict):
        return meta["invoice"]
    return raw


def _valid_url(value):
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and url.hostname in PROVIDER_HOSTS
                 and url.port in (None, 443) and not url.username and not url.password
                 and not url.fragment and "\\" not in value and len(value) <= 4096)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise DetailError("Provider download origin is not supported or is unsafe.")
    return url


def detail_url(value):
    url = _valid_url(value)
    path = url.path.rstrip("/")
    if path.lower().endswith(("/pdf", "/mydata", "/en16931")):
        path = path.rsplit("/", 1)[0]
    return urlunsplit((url.scheme, url.netloc, path + "/myDATA", url.query, ""))


def _public_host(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise DetailError("Provider DNS is temporarily unavailable.", retryable=True) from None
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise DetailError("Provider download resolved to a non-public address.")


def fetch_detail(value):
    target = detail_url(value)
    origin = urlsplit(target).hostname
    _public_host(origin)
    started = time.monotonic()
    try:
        # A separate client has no API keys, authentication, ambient proxy or
        # application cookies. TLS verification remains enabled.
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, trust_env=False) as client:
            for _ in range(3):
                with client.stream("GET", target, headers={"Accept": "application/xml", "User-Agent": "IndeMarketingAnalyzer/1.0"}) as response:
                    if response.is_redirect:
                        redirected = urljoin(target, response.headers.get("location", ""))
                        if _valid_url(redirected).hostname != origin:
                            raise DetailError("Cross-origin provider redirect was blocked.")
                        target = redirected
                        continue
                    if response.status_code != 200:
                        raise DetailError(f"Provider detail returned HTTP {response.status_code}.",
                                          retryable=response.status_code in {408, 429} or response.status_code >= 500)
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=32768):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES or time.monotonic() - started > 30:
                            raise DetailError("Provider detail exceeded the size or time limit.")
                    return parse_detail(bytes(data))
    except httpx.HTTPError:
        # HTTP errors can include private invoice URLs; do not log their text.
        raise DetailError("Provider detail is temporarily unavailable.", retryable=True) from None
    raise DetailError("Too many provider redirects.")


def parse_detail(data):
    if len(data) > MAX_BYTES:
        raise DetailError("Provider detail exceeded the size limit.")
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except DefusedXmlException:
        raise DetailError("Provider response is not a single safe myDATA invoice.") from None
    except ParseError:
        raise DetailError("Provider returned invalid XML; retrieval will be retried.", retryable=True) from None
    if len(list(root.iter())) > 20000:
        raise DetailError("Provider detail exceeded the XML node limit.")
    connector = AADEConnector({})
    payload = {connector._clean_tag(root.tag): connector._xml_to_data(root)}
    invoices = connector._collect_documents(payload)
    if not invoices:
        # Some providers return an HTML error with HTTP 200 during an outage.
        raise DetailError("Provider returned no myDATA invoice; retrieval will be retried.", retryable=True)
    if len(invoices) != 1:
        raise DetailError("Provider response is not a single safe myDATA invoice.")
    return invoices[0]


def _amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) >= Decimal("1000000000"):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise DetailError("Provider detail contains missing or invalid amounts.") from None


def validate_invoice(document, invoice):
    header, issuer, recipient = (invoice.get(key) or {} for key in ("invoiceHeader", "issuer", "counterpart"))
    expected = {"mark": document.mark, "uid": document.uid}
    comparisons = [(invoice.get(key), value) for key, value in expected.items() if value]
    comparisons += [(issuer.get("vatNumber"), document.issuer_vat),
                    (recipient.get("vatNumber"), document.counterpart_vat),
                    (header.get("issueDate"), str(document.issue_date)),
                    (header.get("invoiceType"), document.invoice_type),
                    (header.get("series"), document.series), (header.get("aa"), document.aa),
                    (header.get("currency") or "EUR", document.currency)]
    if not document.mark or any(str(actual or "").strip() != str(wanted or "").strip() for actual, wanted in comparisons):
        raise DetailError("Provider invoice identity does not match the AADE invoice.")
    summary = invoice.get("invoiceSummary") or {}
    amounts = [(_amount(summary.get(key)), _amount(wanted)) for key, wanted in
               (("totalNetValue", document.net_value), ("totalVatAmount", document.vat_amount), ("totalGrossValue", document.gross_value))]
    if any(abs(actual - wanted) > Decimal("0.02") for actual, wanted in amounts):
        raise DetailError("Provider invoice totals do not match AADE.")
    lines = invoice.get("invoiceDetails") or []
    lines = lines if isinstance(lines, list) else [lines]
    if not lines or len(lines) > 1000 or any(not isinstance(line, dict) for line in lines):
        raise DetailError("Provider invoice contains no usable detail lines.")
    numbers = [str(line.get("lineNumber") or "") for line in lines]
    if not all(numbers) or len(set(numbers)) != len(numbers):
        raise DetailError("Provider detail has missing or duplicate line numbers.")
    if not any(line.get("itemCode") or line.get("itemDescr") for line in lines):
        raise DetailError("Provider returned summary lines without products.")
    net = sum((_amount(line.get("netValue")) for line in lines), Decimal("0"))
    vat = sum((_amount(line.get("vatAmount")) for line in lines), Decimal("0"))
    if abs(net - amounts[0][0]) > Decimal("0.02") or abs(vat - amounts[1][0]) > Decimal("0.02"):
        raise DetailError("Provider detail lines do not reconcile to invoice totals.")
    # Store only invoice data, never secondary download links or response HTML.
    return {key: invoice[key] for key in ("mark", "uid", "issuer", "counterpart", "invoiceHeader", "invoiceSummary", "invoiceDetails") if key in invoice}
