from abc import ABC, abstractmethod
from typing import Any

from app.schemas.suppliers import SupplierImportRequest


class SupplierParser(ABC):
    source_type: str

    @abstractmethod
    def parse(self, payload: Any, *, filename: str | None = None) -> SupplierImportRequest:
        """Normalize one supplier source into the shared import contract."""
