from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupplierBase(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, str_strip_whitespace=True)


class SupplierInput(SupplierBase):
    code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    vat_number: str | None = Field(default=None, max_length=32)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    default_currency: Literal["EUR"] = "EUR"
    free_shipping_threshold: Decimal | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=3650)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SupplierSettingsRequest(SupplierBase):
    free_shipping_threshold: Decimal | None = Field(default=None, ge=0)


class SupplierDocumentLineInput(SupplierBase):
    line_number: str | None = Field(default=None, max_length=64)
    line_type: Literal["product", "shipping", "discount", "fee", "other"] = "product"
    supplier_code: str | None = Field(default=None, max_length=255)
    supplier_sku: str | None = Field(default=None, max_length=255)
    supplier_ean: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    manufacturer: str | None = Field(default=None, max_length=255)
    quantity: Decimal = Decimal("0")
    unit: str | None = Field(default=None, max_length=32)
    sales_unit: str | None = Field(default=None, max_length=32)
    pack_quantity: Decimal = Field(default=Decimal("1"), gt=0)
    conversion_factor: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price_before_discount: Decimal = Decimal("0")
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    net_line_total: Decimal | None = None
    vat_rate: Decimal = Field(default=Decimal("0"), ge=0)
    vat_amount: Decimal | None = None
    gross_total: Decimal | None = None
    shipping_type: Literal["INBOUND", "DIRECT_SUPPLIER", "RETURN", "OTHER"] = "INBOUND"
    cbm: Decimal | None = Field(default=None, ge=0)
    weight: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_line(self):
        if self.line_type == "product" and self.quantity <= 0:
            raise ValueError("Product quantity must be positive, including credit-note quantities.")
        if self.line_type == "product" and not any((self.supplier_sku, self.supplier_code, self.supplier_ean, self.description)):
            raise ValueError("A product identifier or description is required.")
        if self.line_type == "product" and self.net_line_total is None and "unit_price_before_discount" not in self.model_fields_set:
            raise ValueError("Product cost must be explicitly supplied; missing cost is not zero.")
        if self.quantity == 0 and self.net_line_total is None:
            raise ValueError("A zero-quantity non-product line requires an explicit net total.")
        if self.pack_quantity != 1 and "conversion_factor" not in self.model_fields_set:
            raise ValueError("Pack quantities require an explicit conversion to OpenCart sales units.")
        return self


class SupplierDocumentInput(SupplierBase):
    document_type: Literal["invoice", "credit_note", "supplier_order", "proforma", "pricelist", "manual", "historical"]
    document_number: str | None = Field(default=None, max_length=160)
    document_date: date
    supplier_order_id: str | None = Field(default=None, max_length=160)
    currency: Literal["EUR"] = "EUR"
    net_products_total: Decimal | None = None
    net_shipping_total: Decimal | None = None
    net_other_total: Decimal | None = None
    vat_total: Decimal | None = None
    gross_total: Decimal | None = None
    lines: list[SupplierDocumentLineInput] = Field(min_length=1, max_length=10000)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_document(self):
        numbers = [line.line_number or str(index) for index, line in enumerate(self.lines, 1)]
        if len(numbers) != len(set(numbers)):
            raise ValueError("Document line numbers must be unique.")
        if self.document_type in {"invoice", "credit_note"} and not self.document_number:
            raise ValueError("Invoices and credit notes require a document number.")
        return self


class SupplierImportRequest(SupplierBase):
    supplier: SupplierInput
    source_type: Literal["json", "email", "pdf", "xls", "xlsx", "xml", "manual"] = "json"
    source_reference: str | None = Field(default=None, max_length=500)
    filename: str | None = Field(default=None, max_length=500)
    documents: list[SupplierDocumentInput] = Field(min_length=1, max_length=1000)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class VerifySupplierMappingRequest(SupplierBase):
    product_catalog_id: UUID
    purchase_unit: str | None = Field(default=None, max_length=32)
    sales_unit: str | None = Field(default=None, max_length=32)
    pack_quantity: Decimal = Field(default=Decimal("1"), gt=0)
    conversion_factor: Decimal = Field(default=Decimal("1"), gt=0)


class ManualSupplierCostRequest(SupplierBase):
    supplier_id: UUID
    supplier_product_map_id: UUID
    purchase_date: date
    net_unit_cost: Decimal = Field(ge=0)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    currency: Literal["EUR"] = "EUR"
    source_reference: str | None = Field(default=None, max_length=500)
    source_confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cost(self):
        if self.net_unit_cost < 0:
            raise ValueError("Net unit cost cannot be negative.")
        return self


class SupplierGmailSyncRequest(SupplierBase):
    date_from: date
    date_to: date
    page_token: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.date_to < self.date_from or (self.date_to - self.date_from).days > 90:
            raise ValueError("Gmail received-date range must be between 0 and 90 days.")
        return self


class SupplierGmailReviewRequest(SupplierBase):
    action: Literal["approve", "reject"]
    confirm_supplier_order: bool = False
    shipping_waived: bool = False
    shipping_net: Decimal | None = Field(default=None, ge=0)
    shipping_vat: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_shipping(self):
        if self.action == "approve" and self.shipping_waived and any(
            value not in (None, Decimal("0")) for value in (self.shipping_net, self.shipping_vat)
        ):
            raise ValueError("Waived freight must have zero net cost and VAT.")
        return self
