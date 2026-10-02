from typing import Any

from app.schemas.suppliers import SupplierImportRequest
from app.supplier_parsers.base import SupplierParser


class NormalizedJsonParser(SupplierParser):
    source_type = "json"

    def parse(self, payload: Any, *, filename: str | None = None) -> SupplierImportRequest:
        request = SupplierImportRequest.model_validate(payload)
        if filename and not request.filename:
            request.filename = filename
        return request
