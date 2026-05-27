from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import httpx


AADE_READ_ONLY_ENDPOINTS = {
    "RequestDocs",
    "RequestTransmittedDocs",
    "RequestMyIncome",
    "RequestMyExpenses",
    "RequestVatInfo",
}

AADE_BLOCKED_ENDPOINT_FRAGMENTS = (
    "Cancel",
    "Classif",
    "Payment",
    "Provider",
    "Send",
)


class AADEConnector:
    """Read-only myDATA connector.

    This connector intentionally supports only AADE read endpoints and only uses
    HTTP GET. It must never be extended with send/cancel/classification calls.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.base_url = str(self.config.get("base_url") or "https://mydatapi.aade.gr/myDATA").rstrip("/") + "/"
        self.timeout = int(self.config.get("timeout_seconds") or 60)

    def fetch_documents(self, date_from: date, date_to: date) -> dict[str, Any]:
        endpoints = self.config.get("endpoints") or ["RequestMyIncome", "RequestMyExpenses"]
        if isinstance(endpoints, str):
            endpoints = [endpoints]

        documents: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []

        with httpx.Client(timeout=self.timeout) as client:
            for endpoint in endpoints:
                endpoint_name = self._validate_endpoint(str(endpoint))
                params = self._params(date_from, date_to, endpoint_name)
                response = client.get(
                    urljoin(self.base_url, endpoint_name),
                    headers=self._headers(),
                    params=params,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"AADE API returned {response.status_code}: {response.text[:800]}")

                payload = self._parse_response(response)
                response_documents = [
                    self._normalise_document(endpoint_name, item)
                    for item in self._collect_documents(payload)
                ]
                documents.extend(response_documents)
                responses.append(
                    {
                        "endpoint": endpoint_name,
                        "params": params,
                        "document_count": len(response_documents),
                    }
                )

        return {
            "documents": documents,
            "summary_rows": self._summary_rows(documents),
            "responses": responses,
        }

    def _validate_endpoint(self, endpoint: str) -> str:
        endpoint = endpoint.strip().strip("/")
        if endpoint not in AADE_READ_ONLY_ENDPOINTS:
            raise ValueError(f"AADE endpoint '{endpoint}' is not in the read-only allowlist.")
        lowered = endpoint.lower()
        if any(fragment.lower() in lowered for fragment in AADE_BLOCKED_ENDPOINT_FRAGMENTS):
            raise ValueError(f"AADE endpoint '{endpoint}' is blocked by the read-only guard.")
        return endpoint

    def _headers(self) -> dict[str, str]:
        user_id = self.config.get("aade_user_id")
        subscription_key = self.config.get("subscription_key")
        if not user_id or not subscription_key:
            raise ValueError("AADE settings require aade_user_id and subscription_key.")
        return {
            "aade-user-id": str(user_id),
            "Ocp-Apim-Subscription-Key": str(subscription_key),
            "Accept": "application/json, application/xml, text/xml",
        }

    def _params(self, date_from: date, date_to: date, endpoint: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "dateFrom": date_from.strftime("%d/%m/%Y"),
            "dateTo": date_to.strftime("%d/%m/%Y"),
        }
        vat_number = self.config.get("vat_number")
        if vat_number:
            params["vatNumber"] = str(vat_number).replace("EL", "").replace("el", "").strip()

        extra_params = self.config.get("extra_params") or {}
        if isinstance(extra_params, dict):
            endpoint_params = extra_params.get(endpoint) or {}
            common_params = extra_params.get("*") or {}
            if isinstance(common_params, dict):
                params.update(common_params)
            if isinstance(endpoint_params, dict):
                params.update(endpoint_params)
        return params

    def _parse_response(self, response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        text = response.text.strip()
        if "json" in content_type or text.startswith("{") or text.startswith("["):
            return response.json()
        if not text:
            return {}
        root = ET.fromstring(text)
        return {self._clean_tag(root.tag): self._xml_to_data(root)}

    def _xml_to_data(self, element: ET.Element) -> Any:
        children: dict[str, Any] = {}
        for child in list(element):
            key = self._clean_tag(child.tag)
            value = self._xml_to_data(child)
            if key in children:
                if not isinstance(children[key], list):
                    children[key] = [children[key]]
                children[key].append(value)
            else:
                children[key] = value

        text = (element.text or "").strip()
        attributes = {self._clean_tag(k): v for k, v in element.attrib.items()}
        if children:
            if attributes:
                children["@attributes"] = attributes
            if text:
                children["text"] = text
            return children
        if attributes:
            return {"@attributes": attributes, "text": text}
        return text

    def _collect_documents(self, payload: Any) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return
            keys = {str(key).lower() for key in value.keys()}
            if (
                "invoiceheader" in keys
                or "invoicesummary" in keys
                or "invoiceDetails" in value
                or "invoice_details" in keys
                or ("mark" in keys and ("uid" in keys or "invoicetype" in keys))
            ):
                documents.append(value)
                return
            for item in value.values():
                visit(item)

        visit(payload)
        return documents

    def _normalise_document(self, endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
        direction = self._direction(endpoint)
        header = self._get(row, "invoiceHeader") or self._get(row, "header") or {}
        summary = self._get(row, "invoiceSummary") or self._get(row, "summary") or {}
        issuer = self._get(row, "issuer") or self._get(header, "issuer") or {}
        counterpart = self._get(row, "counterpart") or self._get(header, "counterpart") or {}

        issue_date = self._date(
            self._pick(header, "issueDate", "dateIssued", "invoiceDate")
            or self._pick(row, "issueDate", "date")
        )
        mark = self._text(self._pick(row, "mark", "invoiceMark", "MARK"))
        uid = self._text(self._pick(row, "uid", "invoiceUid", "UID"))
        series = self._text(self._pick(header, "series", "invoiceSeries") or self._pick(row, "series"))
        aa = self._text(self._pick(header, "aa", "invoiceNumber") or self._pick(row, "aa"))
        invoice_type = self._text(self._pick(header, "invoiceType", "type") or self._pick(row, "invoiceType"))
        currency = self._text(self._pick(header, "currency", "currencyCode") or self._pick(row, "currency")) or "EUR"
        issuer_vat = self._vat(self._pick(issuer, "vatNumber", "vat", "afm", "tin") or self._pick(row, "issuerVat"))
        counterpart_vat = self._vat(
            self._pick(counterpart, "vatNumber", "vat", "afm", "tin") or self._pick(row, "counterpartVat")
        )

        net_value = self._decimal(
            self._pick(summary, "totalNetValue", "netValue", "net")
            or self._pick(row, "totalNetValue", "netValue")
        )
        vat_amount = self._decimal(
            self._pick(summary, "totalVatAmount", "vatAmount", "vat")
            or self._pick(row, "totalVatAmount", "vatAmount")
        )
        gross_value = self._decimal(
            self._pick(summary, "totalGrossValue", "grossValue", "gross")
            or self._pick(row, "totalGrossValue", "grossValue")
        )
        if gross_value == 0 and (net_value or vat_amount):
            gross_value = net_value + vat_amount

        cancelled_by_mark = self._text(self._pick(row, "cancelledByMark", "cancellationMark", "cancelMark"))
        is_cancelled = bool(cancelled_by_mark) or self._bool(self._pick(row, "cancelled", "isCancelled"))
        identity_key = (
            mark
            or uid
            or f"{endpoint}:{issuer_vat or ''}:{counterpart_vat or ''}:{issue_date.isoformat()}:{series or ''}:{aa or ''}:{gross_value}"
        )

        return {
            "source_endpoint": endpoint,
            "identity_key": identity_key,
            "mark": mark,
            "uid": uid,
            "issuer_vat": issuer_vat,
            "counterpart_vat": counterpart_vat,
            "issue_date": issue_date,
            "document_direction": direction,
            "invoice_type": invoice_type,
            "series": series,
            "aa": aa,
            "currency": currency,
            "net_value": net_value,
            "vat_amount": vat_amount,
            "gross_value": gross_value,
            "is_cancelled": is_cancelled,
            "cancelled_by_mark": cancelled_by_mark,
            "raw": row,
        }

    def _summary_rows(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[date, str, str], dict[str, Any]] = defaultdict(
            lambda: {"amount": Decimal("0"), "quantity": 0}
        )
        for document in documents:
            metric_date = document["issue_date"]
            endpoint = document["source_endpoint"]
            direction = document["document_direction"]
            metric_name = f"gross_{direction}"
            key = (metric_date, endpoint, metric_name)
            groups[key]["amount"] += document["gross_value"]
            groups[key]["quantity"] += 1
            if document["is_cancelled"]:
                cancelled_key = (metric_date, endpoint, "cancelled_documents")
                groups[cancelled_key]["quantity"] += 1

        return [
            {
                "metric_date": metric_date,
                "source_endpoint": endpoint,
                "metric_name": metric_name,
                "amount": values["amount"],
                "quantity": values["quantity"],
                "raw": {},
            }
            for (metric_date, endpoint, metric_name), values in groups.items()
        ]

    def _direction(self, endpoint: str) -> str:
        if endpoint in {"RequestTransmittedDocs", "RequestMyIncome"}:
            return "income"
        if endpoint in {"RequestDocs", "RequestMyExpenses"}:
            return "expense"
        return "lookup"

    def _pick(self, row: Any, *keys: str) -> Any:
        if not isinstance(row, dict):
            return None
        for key in keys:
            value = self._get(row, key)
            if value not in (None, ""):
                return value
        return None

    def _get(self, row: Any, key: str) -> Any:
        if not isinstance(row, dict):
            return None
        if key in row:
            return row[key]
        key_lower = key.lower()
        for row_key, value in row.items():
            if str(row_key).lower() == key_lower:
                return value
        return None

    def _date(self, value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(value[:10], fmt).date()
                except ValueError:
                    continue
        return date.today()

    def _decimal(self, value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)

    def _text(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    def _vat(self, value: Any) -> str | None:
        text = self._text(value)
        if not text:
            return None
        return text.replace("EL", "").replace("el", "").strip()

    def _clean_tag(self, tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[1]
        return tag
