from __future__ import annotations

import tempfile
import time
import re
from decimal import Decimal, InvalidOperation
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx
from defusedxml import ElementTree

MAX_FEED_BYTES = 50 * 1024 * 1024
MAX_PRODUCTS = 20000
ALLOWED_HOSTS = {"megapap.com", "www.megapap.com"}
PAKOWORLD_HOSTS = {"pakoworld.com", "www.pakoworld.com"}
ADAPTER_HOSTS = {"megapap": ALLOWED_HOSTS, "pakoworld": PAKOWORLD_HOSTS}
PAKOWORLD_MAX_FEED_BYTES = 75 * 1024 * 1024


def validate_feed_url(value: str, adapter: str = "megapap") -> str:
    hosts = ADAPTER_HOSTS.get(adapter)
    if hosts is None:
        raise ValueError("This supplier XML format is not yet supported.")
    try:
        url = urlsplit(value.strip())
        valid = (url.scheme == "https" and url.hostname in hosts
                 and url.port in (None, 443) and not url.username and not url.password and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"Supplier XML requires an HTTPS URL on {adapter}.com.")
    return value.strip()


def _number(value: str | None) -> str | None:
    if not value:
        return None
    try:
        number = Decimal(value.strip().replace(",", "."))
        if number.is_finite() and 0 <= number < Decimal("1000000000"):
            return str(number)
    except InvalidOperation:
        pass
    return None


def _media_url(value: str | None, hosts: set[str] = ALLOWED_HOSTS) -> str | None:
    if not value:
        return None
    url = urlsplit(value.strip())
    if (url.scheme == "https" and url.hostname in hosts and url.port in (None, 443)
            and not url.query and not url.username and not url.password and not url.fragment):
        return value.strip()
    return None


def parse_packages(dimensions: dict, count: str | None) -> list[dict]:
    """BOX labels are identities, not a list whose order can be assumed."""
    axes = {}
    for axis, value in dimensions.items():
        value = (value or "").strip()
        number = _number(value)
        if number is not None:
            axes[axis] = {"A": number} if count and Decimal(count) == 1 else {}
            continue
        pairs = re.findall(r"BOX\s+([A-Z]|\d{1,2})\s*:\s*([0-9]+(?:[.,][0-9]+)?)", value, re.I)
        # Reject partial/duplicate parses rather than fabricate missing dimensions.
        rest = re.sub(r"BOX\s+([A-Z]|\d{1,2})\s*:\s*([0-9]+(?:[.,][0-9]+)?)", "", value, flags=re.I)
        axes[axis] = {label.upper(): _number(size) for label, size in pairs} if not rest.strip() and len({p[0].upper() for p in pairs}) == len(pairs) else {}
    labels = set(label for values in axes.values() for label in values)
    declared = int(Decimal(count)) if count and Decimal(count) == int(Decimal(count)) and 0 < Decimal(count) <= 30 else 0
    if declared and len(labels) <= declared:
        labels |= {str(i + 1) for i in range(declared)} if labels and all(label.isdigit() for label in labels) else {chr(65 + i) for i in range(declared)}
    return [{"label": f"BOX {label}", **{axis: values.get(label) for axis, values in axes.items()}}
            for label in sorted(labels, key=lambda label: (0, int(label)) if label.isdigit() else (1, label))]


def _parse_catalog(source: BinaryIO, adapter: str) -> list[dict]:
    hosts = ADAPTER_HOSTS[adapter]
    products: list[dict] = []
    seen: set[str] = set()
    root_tag = None
    for event, node in ElementTree.iterparse(source, events=("start", "end"), forbid_dtd=True):
        if root_tag is None:
            root_tag = node.tag
            if root_tag != adapter:
                raise ValueError(f"This XML is not a {adapter.upper()} product catalog.")
        if event != "end" or node.tag != "product":
            continue
        def text(key: str, limit: int = 1000) -> str | None:
            return (node.findtext(key) or "").strip()[:limit] or None
        code, name = text("model", 255), text("name", 500)
        if not code or not name:
            raise ValueError("A supplier product is missing its model or name.")
        if code.casefold() in seen:
            raise ValueError("Duplicate supplier model in XML; the previous catalog was retained.")
        seen.add(code.casefold())
        quantity = _number(text("quantity"))
        dimension_text = {axis: text(tag) for axis, tag in (("width_cm", "comb_width_cm"), ("length_cm", "comb_length_cm"), ("height_cm", "comb_height_cm"))}
        products.append({
            "supplier_code": code, "supplier_sku": text("sku", 255), "ean": text("ean", 64),
            "name": name, "category": text("category"), "image_url": _media_url(text("main_image", 2000), hosts),
            "quantity": int(Decimal(quantity)) if quantity is not None and Decimal(quantity) == int(Decimal(quantity)) else None,
            "wholesale_price_net": _number(text("wholesale_price_without_vat")) if adapter == "megapap" else None,
            "retail_price_gross": _number(text("retail_price_with_vat")),
            "details": {
                "description": text("description", 50000), "availability": text("availability"),
                "manufacturer": text("manufacturer", 255), "minimum": _number(text("minimum")),
                "weboffer_price_gross": _number(text("weboffer_price_with_vat")),
                "volume_item": _number(text("volume_item")), "weight_item": _number(text("weight_item")),
                "packages_per_item": _number(text("packages_per_item")),
                "package_dimensions_raw": dimension_text,
                "packages": parse_packages(dimension_text, _number(text("packages_per_item"))),
                "comb_width_cm": _number(text("comb_width_cm")),
                "comb_length_cm": _number(text("comb_length_cm")),
                "comb_height_cm": _number(text("comb_height_cm")),
                "filters": [{"group": (f.findtext("group") or "")[:255], "value": (f.findtext("value") or "")[:500]}
                            for f in node.findall("./filters/filter")[:100]],
                "images": [value for image in node.findall("./images/image")[:30]
                           if (value := _media_url(image.text, hosts))],
            },
        })
        if adapter == "pakoworld":
            # Pakoworld has no separate SKU. Keep model and EAN distinct and do
            # not infer tax treatment or invoiced costs from dealer price flags.
            products[-1]["details"].update({
                "net_price": _number(text("net_price")), "stock_price": _number(text("stock_price")),
                "has_net_price": text("has_net_price", 20), "sell_step": _number(text("sell_step")),
                "in_stock": text("in_stock", 20), "date_expected": text("date_expected", 100),
                "width": _number(text("width")), "length": _number(text("length")),
                "height": _number(text("height")), "weight": _number(text("weight")),
                "gross_weight": _number(text("gross_weight")), "volume": _number(text("volume")),
                "volume_step": _number(text("volume_step")), "stack_size": _number(text("stack_size")),
                "is_special": text("is_special", 20),
                "assembly_manual": _media_url(text("assembly_manual", 2000), hosts),
                "attributes": [{"id": (item.get("id") or "")[:64], "value": (item.text or "").strip()[:1000]}
                               for item in node.findall("./attributes/attribute")[:100]],
                "categories": [{"id": (item.get("id") or "")[:64], "name": (item.text or "").strip()[:1000]}
                               for item in node.findall("./categories/category")[:100]],
                "components": [{"model": text(f"component_{number}", 255), "pieces": _number(text(f"pieces_{number}"))}
                               for number in range(1, 21) if text(f"component_{number}", 255)],
            })
        node.clear()
        if len(products) > MAX_PRODUCTS:
            raise ValueError("Supplier XML exceeds the product limit.")
    if not products:
        raise ValueError("Supplier XML contains no products; the previous catalog was retained.")
    return products


def parse_megapap_catalog(source: BinaryIO) -> list[dict]:
    return _parse_catalog(source, "megapap")


def parse_pakoworld_catalog(source: BinaryIO) -> list[dict]:
    return _parse_catalog(source, "pakoworld")


def _fetch_catalog(url: str, adapter: str) -> list[dict]:
    url = validate_feed_url(url, adapter)
    max_bytes = PAKOWORLD_MAX_FEED_BYTES if adapter == "pakoworld" else MAX_FEED_BYTES
    started = time.monotonic()
    # Redirects stay on the audited supplier host; no arbitrary server-side URLs.
    with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=False) as client:
        for _ in range(4):
            with client.stream("GET", url, headers={"User-Agent": "IndeMarketingAnalyzer/1.0"}) as response:
                if response.is_redirect:
                    url = validate_feed_url(urljoin(url, response.headers.get("location", "")), adapter)
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Supplier XML returned HTTP {response.status_code}.")
                total = 0
                with tempfile.TemporaryFile() as source:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > max_bytes or time.monotonic() - started > 120:
                            raise ValueError("Supplier XML exceeded the size or time limit.")
                        source.write(chunk)
                    source.seek(0)
                    return _parse_catalog(source, adapter)
    raise ValueError("Too many supplier XML redirects.")


def fetch_megapap_catalog(url: str) -> list[dict]:
    return _fetch_catalog(url, "megapap")


def fetch_pakoworld_catalog(url: str) -> list[dict]:
    return _fetch_catalog(url, "pakoworld")
