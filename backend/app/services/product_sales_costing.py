"""Net sales contract: native OpenCart price/total are net; gross exports must declare tax."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.supplier_costing import decimal_value, money


def present(raw: dict, *keys: str) -> Any | None:
    return next((raw[key] for key in keys if raw.get(key) not in (None, "")), None)


def flag(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class NetSale:
    net_sales: Decimal | None
    quantity: Decimal
    coupon_applied: Decimal
    basis: str


def net_product_sale(raw: dict, price: Any, quantity: Any, coupon_share: Any = 0, *, apply_refunds: bool = True) -> NetSale:
    qty = decimal_value(quantity)
    returned = decimal_value(present(raw, "returned_quantity", "refunded_quantity"))
    if qty < 0 or returned < 0 or returned > qty:
        return NetSale(None, qty, Decimal("0"), "invalid_quantity")
    remaining = qty - returned
    for key in ("net_total", "net_line_total", "gross_total", "total_with_tax", "tax_amount", "line_tax", "subtotal", "line_subtotal", "total", "discount", "discount_amount", "vat_rate", "tax_rate", "refund_net", "refunded_net_total", "refund_gross", "refunded_gross_total", "coupon_share"):
        if raw.get(key) not in (None, "") and decimal_value(raw[key], None) is None:
            return NetSale(None, remaining, Decimal("0"), "invalid_financial_value")
    rate_value = present(raw, "vat_rate", "tax_rate")
    rate = decimal_value(rate_value)
    includes_vat = flag(raw.get("prices_include_vat"))
    coupon_included = flag(raw.get("includes_order_discount"))

    net = present(raw, "net_total", "net_line_total")
    basis = "explicit_net_total"
    if net is not None:
        base = decimal_value(net)
    else:
        gross = present(raw, "gross_total", "total_with_tax")
        if gross is not None:
            tax = present(raw, "tax_amount", "line_tax")
            if tax is not None:
                base = decimal_value(gross) - decimal_value(tax)
            elif rate_value is not None and rate >= 0:
                base = decimal_value(gross) / (1 + rate / 100)
            else:
                return NetSale(None, remaining, Decimal("0"), "missing_vat")
            basis = "gross_less_vat"
        else:
            subtotal = present(raw, "subtotal", "line_subtotal")
            total = present(raw, "total")
            # Native OpenCart product.total already contains per-line discounts.
            if subtotal is None and total is not None:
                base = decimal_value(total)
            else:
                base = decimal_value(subtotal) if subtotal is not None else decimal_value(price) * qty
                base -= abs(decimal_value(present(raw, "discount", "discount_amount")))
            if includes_vat:
                if rate_value is None or rate < 0:
                    return NetSale(None, remaining, Decimal("0"), "missing_vat")
                base /= 1 + rate / 100
            basis = "gross_price_less_vat" if includes_vat else "opencart_net"
    explicit_coupon = present(raw, "coupon_share")
    coupon = Decimal("0") if coupon_included else (-abs(decimal_value(explicit_coupon)) if explicit_coupon is not None else decimal_value(coupon_share))
    if includes_vat and coupon:
        if rate_value is None or rate < 0:
            return NetSale(None, remaining, coupon, "missing_discount_vat")
        coupon /= 1 + rate / 100
    base += coupon
    if not apply_refunds:
        return NetSale(money(base), qty, money(coupon), basis)
    refund_net = present(raw, "refund_net", "refunded_net_total")
    refund_gross = present(raw, "refund_gross", "refunded_gross_total")
    if refund_net is not None:
        base -= abs(decimal_value(refund_net))
    elif refund_gross is not None:
        if rate_value is None or rate < 0:
            return NetSale(None, remaining, coupon, "missing_refund_vat")
        base -= abs(decimal_value(refund_gross)) / (1 + rate / 100)
    elif returned and qty:
        base *= remaining / qty
    return NetSale(money(base), remaining, money(coupon), basis)


def allocate_coupon(bases: list[Decimal], coupon: Decimal) -> list[Decimal]:
    positive = [max(base, Decimal("0")) for base in bases]
    total = sum(positive, Decimal("0"))
    if not total:
        return [Decimal("0") for _ in bases]
    shares = [money(coupon * base / total) for base in positive]
    last = max(index for index, base in enumerate(positive) if base)
    shares[last] += money(coupon) - sum(shares, Decimal("0"))
    return shares
