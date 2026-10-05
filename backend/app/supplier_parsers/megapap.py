from __future__ import annotations

import io
import re
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any

import pdfplumber

from app.schemas.suppliers import SupplierImportRequest
from app.services.supplier_costing import money, normalize_name
from app.supplier_parsers.base import SupplierParser


class MegapapParseError(ValueError):
    pass


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.stack: list[list[list[str]]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.text: list[str] = []
        self.hidden = 0
        self.colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag == "table":
            self.stack.append([])
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
            span = dict(attrs).get("colspan", "1") or "1"
            self.colspan = min(20, max(1, int(span))) if span.isdigit() else 1
        elif tag == "br":
            self.text.append("\n")
            if self.cell is not None:
                self.cell.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.cell is not None:
                self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join("".join(self.cell).split()))
                self.row.extend([""] * (self.colspan - 1))
            self.cell = None
            self.text.append(" ")
        elif tag == "tr" and self.row is not None:
            if self.stack:
                self.stack[-1].append(self.row)
            self.row = None
            self.text.append("\n")
        elif tag == "table" and self.stack:
            self.tables.append(self.stack.pop())
        elif tag in {"p", "div"}:
            self.text.append("\n")


def _amount(text: Any) -> Decimal:
    value = str(text or "").strip().replace("€", "").replace("EUR", "").replace("\xa0", "").replace(" ", "")
    if not re.fullmatch(r"\d+|\d+,\d{1,4}|\d{1,3}(?:\.\d{3})+,\d{1,4}|\d+\.\d{1,2}", value):
        raise MegapapParseError("MEGAPAP amount is missing or unsupported.")
    return money(value)


class MegapapParser(SupplierParser):
    source_type = "pdf"

    def parse(self, payload: Any, *, filename: str | None = None) -> SupplierImportRequest:
        if isinstance(payload, bytes):
            if not payload.startswith(b"%PDF") or len(payload) > 10 * 1024 * 1024:
                raise MegapapParseError("Only text-based MEGAPAP PDFs up to 10 MB are supported.")
            try:
                with pdfplumber.open(io.BytesIO(payload)) as pdf:
                    if not 1 <= len(pdf.pages) <= 25:
                        raise MegapapParseError("MEGAPAP PDF page limit exceeded.")
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                    tables = [table for page in pdf.pages for table in page.extract_tables()]
            except MegapapParseError:
                raise
            except Exception:
                raise MegapapParseError("MEGAPAP PDF cannot be read; manual review required.") from None
            source_type = "pdf"
        elif isinstance(payload, str):
            if len(payload) > 2 * 1024 * 1024:
                raise MegapapParseError("MEGAPAP email body is too large.")
            html = _Tables()
            html.feed(payload)
            text, tables = "".join(html.text), html.tables
            source_type = "email"
        else:
            raise MegapapParseError("Unsupported MEGAPAP source.")
        return self._normalize(text, tables, filename, source_type)

    def _normalize(self, text, tables, filename, source_type):
        if "megapap" not in text.casefold():
            raise MegapapParseError("Document does not identify MEGAPAP.")
        order = re.search(r"Αριθμός\s+παραγγελίας\s*:\s*([A-Za-z0-9_-]+)", text, re.I)
        issued = re.search(r"Ημερομηνία\s+καταχώρησης\s*:\s*(\d{2}/\d{2}/\d{4})", text, re.I)
        if not order or not issued:
            raise MegapapParseError("MEGAPAP order identity/date missing; document needs review.")
        try:
            document_date = datetime.strptime(issued.group(1), "%d/%m/%Y").date()
        except ValueError:
            raise MegapapParseError("Invalid MEGAPAP document date.") from None

        lines, totals = [], []
        columns = [normalize_name(value) for value in ["Όνομα προϊόντος", "Κωδικός", "Τιμή", "SKU", "Σύνολο"]]
        for table in tables:
            active = False
            indexes = []
            for row in table:
                headers = [normalize_name(cell) for cell in row]
                if all(column in headers for column in columns):
                    indexes = [headers.index(column) for column in columns]
                    active = True
                    continue
                if not active or not any(cell for cell in row):
                    continue
                if len(row) <= max(indexes):
                    raise MegapapParseError("MEGAPAP table columns are incomplete.")
                name, code, price, sku, total = [row[index] for index in indexes]
                if sku:
                    qty = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*[x×]\s+(.+)", name or "", re.S)
                    if not qty or not code:
                        raise MegapapParseError("MEGAPAP quantity/code missing; line needs review.")
                    quantity = _amount(qty.group(1))
                    unit_price, net = _amount(price), _amount(total)
                    if quantity <= 0 or abs(quantity * unit_price - net) > Decimal("0.02"):
                        raise MegapapParseError("MEGAPAP line price/quantity does not reconcile.")
                    lines.append({"line_number": str(len(lines) + 1), "supplier_sku": str(sku).strip(),
                        "supplier_code": str(code).strip(), "description": " ".join(qty.group(2).split()),
                        "quantity": quantity, "unit": "piece", "unit_price_before_discount": unit_price,
                        "net_line_total": net})
                elif row[-1] and row[0]:
                    totals.append((" ".join(str(row[0]).split()), _amount(row[-1])))
                else:
                    raise MegapapParseError("Unrecognized MEGAPAP table row; manual review required.")
        if not lines:
            raise MegapapParseError("No supported MEGAPAP product table; scanned/changed layouts need review.")

        subtotal = gross = vat = rate = None
        shipping = []
        for label, amount in totals:
            title = normalize_name(label)
            if title == "μερικο συνολο":
                if subtotal is not None:
                    raise MegapapParseError("Repeated MEGAPAP totals; manual review required.")
                subtotal = amount
            elif title == "γενικο συνολο":
                if gross is not None:
                    raise MegapapParseError("Repeated MEGAPAP totals; manual review required.")
                gross = amount
            elif re.match(r"φπα\s+\d", title):
                match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", label)
                if vat is not None or not match:
                    raise MegapapParseError("Mixed or unknown MEGAPAP VAT rates need review.")
                rate, vat = _amount(match.group(1)), amount
            else:
                # Known logistics labels only. Discounts/fees must not become freight.
                if not any(word in title for word in ("αποστολ", "μεταφορ", "παραλαβ", "shipping")):
                    raise MegapapParseError("Unsupported MEGAPAP charge; manual review required.")
                shipping.append(amount)
        if any(value is None for value in (subtotal, gross, vat, rate)) or len(shipping) > 1:
            raise MegapapParseError("MEGAPAP totals/VAT/freight are incomplete or ambiguous.")
        product_net = sum((line["net_line_total"] for line in lines), Decimal("0"))
        freight = shipping[0] if shipping else None
        if abs(product_net - subtotal) > Decimal("0.02"):
            raise MegapapParseError("MEGAPAP product subtotal does not reconcile.")
        if freight is None or abs(subtotal + vat + freight - gross) > Decimal("0.02"):
            raise MegapapParseError("MEGAPAP freight is missing or document total does not reconcile.")
        if abs(subtotal * rate / 100 - vat) > Decimal("0.02"):
            raise MegapapParseError("MEGAPAP VAT basis differs from supported product-only VAT; manual review required.")
        for line in lines:
            line["vat_rate"] = rate
            line["vat_amount"] = (line["net_line_total"] * rate / 100).quantize(Decimal("0.01"))
        # Keep the displayed freight pending. Zero here is not a confirmed tax exemption.
        lines.append({"line_number": "shipping", "line_type": "shipping", "description": "Supplier shipping",
            "quantity": 0, "net_line_total": freight, "vat_amount": 0, "shipping_type": "INBOUND",
            "raw_metadata": {"tax_basis_unconfirmed": True, "displayed_amount": str(freight)}})
        return SupplierImportRequest.model_validate({"supplier": {"code": "MEGAPAP", "name": "MEGAPAP"},
            "source_type": source_type, "filename": filename, "documents": [{
                "document_type": "supplier_order", "document_number": order.group(1),
                "supplier_order_id": order.group(1), "document_date": document_date,
                "net_products_total": subtotal, "net_shipping_total": freight, "vat_total": vat,
                "gross_total": gross, "lines": lines,
                "raw_metadata": {"parser": "megapap_order_v1", "review_required": ["supplier_order_not_invoice", "freight_tax_basis_unconfirmed"]},
            }]})
