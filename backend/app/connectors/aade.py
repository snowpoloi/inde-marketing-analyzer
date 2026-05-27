from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin
import re
import time
import xml.etree.ElementTree as ET

import httpx


AADE_READ_ONLY_ENDPOINTS = {
    "RequestDocs",
    "RequestTransmittedDocs",
    "RequestMyIncome",
    "RequestMyExpenses",
    "RequestVatInfo",
}

AADE_DOCUMENT_ENDPOINTS = {"RequestDocs", "RequestTransmittedDocs"}
AADE_BOOK_ENDPOINTS = {"RequestMyIncome", "RequestMyExpenses"}
AADE_VAT_ENDPOINTS = {"RequestVatInfo"}

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
        self.max_pages = min(25, max(1, self._int(self.config.get("max_pages")) or 2))
        self.max_retries = min(3, max(0, self._int(self.config.get("max_retries")) or 1))
        self.page_delay_seconds = min(10.0, max(0.0, self._float(self.config.get("page_delay_seconds"), 2.0)))
        self.retry_after_max_seconds = min(60, max(0, self._int(self.config.get("retry_after_max_seconds")) or 20))

    def fetch_documents(self, date_from: date, date_to: date) -> dict[str, Any]:
        endpoints = self.config.get("endpoints") or ["RequestMyIncome", "RequestMyExpenses"]
        if isinstance(endpoints, str):
            endpoints = [endpoints]

        documents: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []
        cursor: dict[str, dict[str, str]] = {}

        with httpx.Client(timeout=self.timeout) as client:
            request_count = 0
            for endpoint in endpoints:
                endpoint_name = self._validate_endpoint(str(endpoint))
                endpoint_documents: list[dict[str, Any]] = []
                endpoint_max_mark = self._endpoint_mark(endpoint_name)
                next_partition_key: str | None = None
                next_row_key: str | None = None

                for page in range(1, self.max_pages + 1):
                    params = self._params(date_from, date_to, endpoint_name, next_partition_key, next_row_key)
                    if request_count and self.page_delay_seconds:
                        time.sleep(self.page_delay_seconds)
                    response = self._request_get(client, endpoint_name, params)
                    request_count += 1
                    if response.status_code >= 400:
                        raise RuntimeError(f"AADE API returned {response.status_code}: {response.text[:800]}")

                    payload = self._parse_response(response)
                    response_book_rows = (
                        [
                            self._normalise_book_info(endpoint_name, item)
                            for item in self._collect_book_info(payload)
                        ]
                        if endpoint_name in AADE_BOOK_ENDPOINTS
                        else []
                    )
                    response_documents = [
                        self._normalise_document(endpoint_name, item)
                        for item in self._collect_documents(payload)
                    ]
                    response_cancellations = (
                        [
                            self._normalise_cancellation(endpoint_name, item)
                            for item in self._collect_cancellations(payload)
                        ]
                        if endpoint_name in AADE_DOCUMENT_ENDPOINTS
                        else []
                    )
                    response_vat_rows = (
                        [
                            self._normalise_vat_info(endpoint_name, item)
                            for item in self._collect_vat_info(payload)
                        ]
                        if endpoint_name in AADE_VAT_ENDPOINTS
                        else []
                    )
                    response_rows = response_documents + response_book_rows + response_cancellations + response_vat_rows
                    endpoint_documents.extend(response_rows)
                    endpoint_max_mark = max(endpoint_max_mark, self._max_response_mark(payload, response_rows))
                    next_partition_key, next_row_key = self._next_partition(payload)
                    responses.append(
                        {
                            "endpoint": endpoint_name,
                            "page": page,
                            "params": self._redacted_params(params),
                            "document_count": sum(int(item.get("document_count") or 1) for item in response_rows),
                            "full_document_count": len(response_documents),
                            "book_row_count": len(response_book_rows),
                            "book_document_count": sum(
                                int(item.get("document_count") or 1) for item in response_book_rows
                            ),
                            "cancellation_count": len(response_cancellations),
                            "vat_row_count": len(response_vat_rows),
                            "has_next_page": bool(next_partition_key and next_row_key),
                        }
                    )
                    if not next_partition_key or not next_row_key:
                        break

                documents.extend(endpoint_documents)
                if endpoint_name in AADE_DOCUMENT_ENDPOINTS:
                    cursor[endpoint_name] = {"mark": str(endpoint_max_mark)}

        return {
            "documents": documents,
            "summary_rows": self._summary_rows(documents),
            "responses": responses,
            "cursor": cursor,
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

    def _request_get(self, client: httpx.Client, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        url = urljoin(self.base_url, endpoint)
        for attempt in range(self.max_retries + 1):
            response = client.get(url, headers=self._headers(), params=params)
            if response.status_code != 429:
                return response

            retry_after = self._retry_after_seconds(response)
            if retry_after > self.retry_after_max_seconds:
                raise RuntimeError(
                    f"AADE rate limit reached. Try again in {retry_after} seconds before running sync again."
                )
            if attempt >= self.max_retries:
                raise RuntimeError(
                    f"AADE rate limit reached after {attempt + 1} attempts. Try again in {retry_after} seconds."
                )
            time.sleep(max(float(retry_after), self.page_delay_seconds))
        return response

    def _retry_after_seconds(self, response: httpx.Response) -> int:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            return max(1, self._int(retry_after))
        match = re.search(r"try again in\s+(\d+)\s+seconds", response.text, flags=re.IGNORECASE)
        if match:
            return max(1, self._int(match.group(1)))
        return max(1, min(self.retry_after_max_seconds, 2))

    def _params(
        self,
        date_from: date,
        date_to: date,
        endpoint: str,
        next_partition_key: str | None = None,
        next_row_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "dateFrom": date_from.strftime("%d/%m/%Y"),
            "dateTo": date_to.strftime("%d/%m/%Y"),
        }
        if endpoint in AADE_DOCUMENT_ENDPOINTS:
            params["mark"] = self._endpoint_mark(endpoint)
        vat_number = self.config.get("vat_number")
        if endpoint in AADE_VAT_ENDPOINTS:
            params["GroupedPerDay"] = str(self._bool(self.config.get("vat_grouped_per_day"))).lower()
        if vat_number and self._include_entity_vat_number(endpoint):
            params["entityVatNumber"] = str(vat_number).replace("EL", "").replace("el", "").strip()

        if next_partition_key and next_row_key:
            params["nextPartitionKey"] = next_partition_key
            params["nextRowKey"] = next_row_key

        extra_params = self.config.get("extra_params") or {}
        if isinstance(extra_params, dict):
            endpoint_params = extra_params.get(endpoint) or {}
            common_params = extra_params.get("*") or {}
            if isinstance(common_params, dict):
                params.update(common_params)
            if isinstance(endpoint_params, dict):
                params.update(endpoint_params)
        if endpoint in AADE_DOCUMENT_ENDPOINTS:
            params["mark"] = self._int(params.get("mark"))
        return params

    def _include_entity_vat_number(self, endpoint: str) -> bool:
        if endpoint in AADE_DOCUMENT_ENDPOINTS:
            return self._bool(self.config.get("representative_mode") or self.config.get("send_entity_vat_number"))
        return True

    def _endpoint_mark(self, endpoint: str) -> int:
        cursor = self.config.get("cursor") or self.config.get("cursors") or {}
        if isinstance(cursor, dict):
            endpoint_cursor = cursor.get(endpoint) or {}
            if isinstance(endpoint_cursor, dict):
                return self._int(endpoint_cursor.get("mark"))
        marks = self.config.get("marks") or {}
        if isinstance(marks, dict):
            return self._int(marks.get(endpoint))
        return self._int(self.config.get("mark"))

    def _redacted_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in params.items() if key not in {"Ocp-Apim-Subscription-Key"}}

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
                or "invoicedetails" in keys
                or "invoice_details" in keys
                or ("mark" in keys and ("uid" in keys or "invoicetype" in keys))
            ):
                documents.append(value)
                return
            for item in value.values():
                visit(item)

        visit(payload)
        return documents

    def _collect_book_info(self, payload: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return
            keys = {str(key).lower() for key in value.keys()}
            if "issuedate" in keys and "invtype" in keys and (
                "netvalue" in keys or "vatamount" in keys or "grossvalue" in keys or "count" in keys
            ):
                rows.append(value)
                return
            for item in value.values():
                visit(item)

        visit(payload)
        return rows

    def _collect_cancellations(self, payload: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return
            keys = {str(key).lower() for key in value.keys()}
            if "invoicemark" in keys and "cancellationmark" in keys and "cancellationdate" in keys:
                rows.append(value)
                return
            for item in value.values():
                visit(item)

        visit(payload)
        return rows

    def _collect_vat_info(self, payload: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return
            keys = {str(key).lower() for key in value.keys()}
            if "issuedate" in keys and any(key.startswith("vat") for key in keys):
                rows.append(value)
                return
            for item in value.values():
                visit(item)

        visit(payload)
        return rows

    def _next_partition(self, payload: Any) -> tuple[str | None, str | None]:
        partition = self._find_first(payload, "nextPartitionKey")
        row = self._find_first(payload, "nextRowKey")
        partition_text = self._text(partition)
        row_text = self._text(row)
        return partition_text, row_text

    def _find_first(self, value: Any, key: str) -> Any:
        if isinstance(value, list):
            for item in value:
                found = self._find_first(item, key)
                if found not in (None, ""):
                    return found
            return None
        if not isinstance(value, dict):
            return None
        key_lower = key.lower()
        for row_key, row_value in value.items():
            if str(row_key).lower() == key_lower:
                return row_value
            found = self._find_first(row_value, key)
            if found not in (None, ""):
                return found
        return None

    def _max_mark(self, documents: list[dict[str, Any]]) -> int:
        marks = [
            self._int(document.get("mark") or document.get("max_mark") or document.get("cancelled_by_mark"))
            for document in documents
        ]
        return max(marks, default=0)

    def _max_response_mark(self, payload: Any, rows: list[dict[str, Any]]) -> int:
        marks = [self._max_mark(rows)]
        for key in ("mark", "invoiceMark", "cancellationMark", "classificationMark", "paymentMethodMark", "maxMark"):
            marks.extend(self._find_all_ints(payload, key))
        return max(marks, default=0)

    def _find_all_ints(self, value: Any, key: str) -> list[int]:
        if isinstance(value, list):
            found: list[int] = []
            for item in value:
                found.extend(self._find_all_ints(item, key))
            return found
        if not isinstance(value, dict):
            return []
        found = []
        key_lower = key.lower()
        for row_key, row_value in value.items():
            if str(row_key).lower() == key_lower:
                found.append(self._int(row_value))
            found.extend(self._find_all_ints(row_value, key))
        return [item for item in found if item]

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
            "document_count": 1,
            "is_cancelled": is_cancelled,
            "cancelled_by_mark": cancelled_by_mark,
            "raw": {**row, "document_count": 1},
        }

    def _normalise_cancellation(self, endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
        direction = self._direction(endpoint)
        issue_date = self._date(self._pick(row, "cancellationDate", "issueDate", "date"))
        invoice_mark = self._text(self._pick(row, "invoiceMark", "mark"))
        cancellation_mark = self._text(self._pick(row, "cancellationMark", "cancelledByMark"))
        identity_key = f"{endpoint}:cancelled:{invoice_mark or ''}:{cancellation_mark or ''}:{issue_date.isoformat()}"

        return {
            "source_endpoint": endpoint,
            "identity_key": identity_key,
            "mark": invoice_mark,
            "uid": None,
            "issuer_vat": None,
            "counterpart_vat": None,
            "issue_date": issue_date,
            "document_direction": direction,
            "invoice_type": None,
            "series": None,
            "aa": None,
            "currency": "EUR",
            "net_value": Decimal("0"),
            "vat_amount": Decimal("0"),
            "gross_value": Decimal("0"),
            "document_count": 1,
            "is_cancelled": True,
            "cancelled_by_mark": cancellation_mark,
            "raw": {**row, "document_count": 1, "record_type": "cancellation"},
        }

    def _normalise_book_info(self, endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
        direction = self._direction(endpoint)
        issue_date = self._date(self._pick(row, "issueDate", "date"))
        invoice_type = self._text(self._pick(row, "invType", "invoiceType", "type"))
        counter_vat = self._vat(self._pick(row, "counterVatNumber", "counterpartVat", "vatNumber"))
        own_vat = self._vat(self.config.get("vat_number"))
        net_value = self._decimal(self._pick(row, "netValue", "totalNetValue", "net"))
        vat_amount = self._decimal(self._pick(row, "vatAmount", "totalVatAmount", "vat"))
        gross_value = self._decimal(self._pick(row, "grossValue", "totalGrossValue", "gross"))
        if gross_value == 0 and (net_value or vat_amount):
            gross_value = net_value + vat_amount

        document_count = self._int(self._pick(row, "count", "quantity")) or 1
        min_mark = self._text(self._pick(row, "minMark", "min_mark"))
        max_mark = self._text(self._pick(row, "maxMark", "max_mark"))
        self_pricing = self._text(self._pick(row, "selfPricing", "self_pricing"))
        invoice_detail_type = self._text(self._pick(row, "invoiceDetailType", "invoice_detail_type"))
        is_cancelled = self._bool(self._pick(row, "cancelled", "isCancelled"))
        if direction == "income":
            issuer_vat = own_vat
            counterpart_vat = counter_vat
        elif direction == "expense":
            issuer_vat = counter_vat
            counterpart_vat = own_vat
        else:
            issuer_vat = own_vat
            counterpart_vat = counter_vat

        raw = {**row, "document_count": document_count, "record_type": "book_info"}
        identity_key = (
            f"{endpoint}:{issue_date.isoformat()}:{direction}:{counter_vat or ''}:{invoice_type or ''}:"
            f"{self_pricing or ''}:{invoice_detail_type or ''}:{net_value}:{vat_amount}:{gross_value}:"
            f"{document_count}:{min_mark or ''}:{max_mark or ''}"
        )

        return {
            "source_endpoint": endpoint,
            "identity_key": identity_key,
            "mark": max_mark or min_mark,
            "max_mark": max_mark,
            "uid": None,
            "issuer_vat": issuer_vat,
            "counterpart_vat": counterpart_vat,
            "issue_date": issue_date,
            "document_direction": direction,
            "invoice_type": invoice_type,
            "series": None,
            "aa": None,
            "currency": "EUR",
            "net_value": net_value,
            "vat_amount": vat_amount,
            "gross_value": gross_value,
            "document_count": document_count,
            "is_cancelled": is_cancelled,
            "cancelled_by_mark": None,
            "raw": raw,
        }

    def _normalise_vat_info(self, endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
        issue_date = self._date(self._pick(row, "IssueDate", "issueDate", "date"))
        mark = self._text(self._pick(row, "Mark", "mark"))
        vat_amount = sum(
            (self._decimal(value) for key, value in row.items() if str(key).lower().startswith("vat")),
            Decimal("0"),
        )
        is_cancelled = self._bool(self._pick(row, "IsCancelled", "isCancelled", "cancelled"))
        identity_key = f"{endpoint}:vat:{mark or ''}:{issue_date.isoformat()}:{vat_amount}"

        return {
            "source_endpoint": endpoint,
            "identity_key": identity_key,
            "mark": mark,
            "uid": None,
            "issuer_vat": None,
            "counterpart_vat": None,
            "issue_date": issue_date,
            "document_direction": "vat",
            "invoice_type": None,
            "series": None,
            "aa": None,
            "currency": "EUR",
            "net_value": Decimal("0"),
            "vat_amount": vat_amount,
            "gross_value": Decimal("0"),
            "document_count": 1,
            "is_cancelled": is_cancelled,
            "cancelled_by_mark": None,
            "raw": {**row, "document_count": 1, "record_type": "vat_info"},
        }

    def _summary_rows(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[date, str, str], dict[str, Any]] = defaultdict(
            lambda: {"amount": Decimal("0"), "quantity": 0}
        )
        for document in documents:
            metric_date = document["issue_date"]
            endpoint = document["source_endpoint"]
            direction = document["document_direction"]
            document_count = self._int(document.get("document_count")) or 1
            metric_name = "vat_total" if direction == "vat" else f"gross_{direction}"
            key = (metric_date, endpoint, metric_name)
            groups[key]["amount"] += document["vat_amount"] if direction == "vat" else document["gross_value"]
            groups[key]["quantity"] += document_count
            if document["is_cancelled"]:
                cancelled_key = (metric_date, endpoint, "cancelled_documents")
                groups[cancelled_key]["quantity"] += document_count

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

    def _int(self, value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(Decimal(str(value).replace(",", ".")))
        except (InvalidOperation, ValueError):
            return 0

    def _float(self, value: Any, default: float) -> float:
        if value in (None, ""):
            return default
        try:
            return float(Decimal(str(value).replace(",", ".")))
        except (InvalidOperation, ValueError):
            return default

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
