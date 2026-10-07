from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Iterable


MONEY = Decimal("0.0001")
PERCENT = Decimal("0.01")

SOURCE_PRIORITY = {
    "aade_invoice": -1,
    "invoice": 0,
    "credit_note": 0,
    "supplier_order": 1,
    "proforma": 1,
    "pricelist": 2,
    "manual": 3,
    "historical": 4,
}


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    text = str(value).strip().replace("\u00a0", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        result = Decimal(text)
        return result if result.is_finite() else default
    except Exception:
        return default


def money(value: Any) -> Decimal:
    return decimal_value(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def normalize_identifier(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9α-ω]+", text))


def supplier_mapping_identity(supplier_sku: Any, supplier_ean: Any, supplier_code: Any, description: Any) -> str:
    for prefix, value in (("sku", supplier_sku), ("ean", supplier_ean), ("code", supplier_code)):
        normalized = normalize_identifier(value)
        if normalized:
            return f"{prefix}:{normalized}"
    normalized = normalize_name(description) or "unknown"
    if len(normalized) > 600:
        return "description:sha256:" + hashlib.sha256(normalized.encode()).hexdigest()
    return f"description:{normalized}"


def calculate_purchase_line(
    *,
    quantity: Any,
    unit_price_before_discount: Any,
    discount_percent: Any = 0,
    discount_amount: Any = 0,
    net_line_total: Any | None = None,
    conversion_factor: Any = 1,
) -> tuple[Decimal, Decimal]:
    qty = decimal_value(quantity)
    factor = decimal_value(conversion_factor, Decimal("1"))
    if factor <= 0:
        raise ValueError("Conversion factor must be positive.")

    if net_line_total not in (None, ""):
        net_total = money(net_line_total)
    else:
        unit_price = decimal_value(unit_price_before_discount)
        base_total = qty * unit_price
        explicit_discount = decimal_value(discount_amount)
        percent_discount = base_total * decimal_value(discount_percent) / Decimal("100")
        net_total = money(base_total - (explicit_discount if explicit_discount else percent_discount))

    sales_units = qty * factor
    net_unit_cost = money(net_total / sales_units) if sales_units else Decimal("0")
    return net_total, net_unit_cost


def margin_metrics(net_sales: Any, quantity: Any, unit_cost: Any | None) -> dict[str, Decimal | None]:
    sales = money(net_sales)
    qty = decimal_value(quantity)
    if unit_cost is None:
        return {"net_sales": sales, "cogs": None, "gross_profit": None, "margin_percent": None}
    cogs = money(qty * decimal_value(unit_cost))
    gross_profit = money(sales - cogs)
    margin_percent = (
        (gross_profit / sales * Decimal("100")).quantize(PERCENT, rounding=ROUND_HALF_UP)
        if sales != 0
        else None
    )
    return {
        "net_sales": sales,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "margin_percent": margin_percent,
    }


@dataclass(frozen=True)
class CostOption:
    key: str
    purchase_date: date
    source_type: str
    net_unit_cost: Decimal
    confidence: Decimal = Decimal("1")
    status: str = "active"


def select_cost_as_of(costs: Iterable[CostOption], as_of: date) -> CostOption | None:
    eligible = [
        cost
        for cost in costs
        if cost.purchase_date <= as_of and cost.status == "active" and cost.net_unit_cost >= 0
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda cost: (
            SOURCE_PRIORITY.get(cost.source_type, 99),
            -cost.purchase_date.toordinal(),
            -cost.confidence,
            cost.key,
        ),
    )


@dataclass(frozen=True)
class CatalogIdentity:
    key: str
    sku: str | None
    model: str | None
    product_id: str | None
    ean: str | None
    upc: str | None
    mpn: str | None
    name: str
    manufacturer: str | None = None


@dataclass(frozen=True)
class MatchCandidate:
    catalog: CatalogIdentity
    method: str
    confidence: Decimal


def exact_catalog_matches(
    catalogs: Iterable[CatalogIdentity],
    *,
    supplier: str,
    supplier_sku: Any = None,
    supplier_ean: Any = None,
    supplier_code: Any = None,
) -> list[MatchCandidate]:
    supplier_name = normalize_name(supplier)
    sku = normalize_identifier(supplier_sku)
    ean = normalize_identifier(supplier_ean)
    code = normalize_identifier(supplier_code)
    matches: dict[str, MatchCandidate] = {}

    def add(catalog: CatalogIdentity, method: str, confidence: str) -> None:
        candidate = MatchCandidate(catalog, method, Decimal(confidence))
        existing = matches.get(catalog.key)
        if existing is None or candidate.confidence > existing.confidence:
            matches[catalog.key] = candidate

    catalog_rows = list(catalogs)
    if "megapap" in supplier_name:
        # MEGAPAP's supplier SKU identifies the OpenCart model, not its internal code.
        return [MatchCandidate(catalog, "exact_supplier_sku_to_model", Decimal("0.99"))
                for catalog in catalog_rows if sku and sku == normalize_identifier(catalog.model)]
    if sku:
        for catalog in catalog_rows:
            if sku == normalize_identifier(catalog.sku):
                add(catalog, "exact_supplier_sku_to_sku", "1")
            elif sku == normalize_identifier(catalog.model):
                add(catalog, "exact_supplier_sku_to_model", "0.99")

    if ean:
        for catalog in catalog_rows:
            if ean in {normalize_identifier(catalog.ean), normalize_identifier(catalog.upc)}:
                add(catalog, "exact_ean", "0.99")

    if code and "megapap" not in supplier_name:
        for catalog in catalog_rows:
            if code in {
                normalize_identifier(catalog.sku),
                normalize_identifier(catalog.model),
                normalize_identifier(catalog.mpn),
            }:
                add(catalog, "exact_supplier_code", "0.90")

    ordered = sorted(matches.values(), key=lambda candidate: (-candidate.confidence, candidate.catalog.name))
    # Only the highest-priority exact tier is eligible; ties still require review.
    return [candidate for candidate in ordered if candidate.confidence == ordered[0].confidence] if ordered else []


def fuzzy_catalog_candidates(
    catalogs: Iterable[CatalogIdentity],
    *,
    description: Any,
    manufacturer: Any = None,
    limit: int = 5,
) -> list[MatchCandidate]:
    source_name = normalize_name(description)
    source_manufacturer = normalize_name(manufacturer)
    if not source_name:
        return []

    candidates: list[MatchCandidate] = []
    for catalog in catalogs:
        target_name = normalize_name(catalog.name)
        if not target_name:
            continue
        score = Decimal(str(SequenceMatcher(None, source_name, target_name).ratio()))
        if source_manufacturer and source_manufacturer == normalize_name(catalog.manufacturer):
            score = min(Decimal("1"), score + Decimal("0.08"))
        if score >= Decimal("0.55"):
            candidates.append(MatchCandidate(catalog, "name_candidate_only", score.quantize(Decimal("0.0001"))))
    return sorted(candidates, key=lambda candidate: (-candidate.confidence, candidate.catalog.name))[:limit]
