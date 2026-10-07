from __future__ import annotations

import tempfile
import time
from decimal import Decimal, InvalidOperation
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx
from defusedxml import ElementTree

MAX_FEED_BYTES = 50 * 1024 * 1024
MAX_PRODUCTS = 20000
ALLOWED_HOSTS = {"megapap.com", "www.megapap.com"}


def validate_feed_url(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        valid = (url.scheme == "https" and url.hostname in ALLOWED_HOSTS
                 and url.port in (None, 443) and not url.username and not url.password and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("MEGAPAP XML requires an HTTPS URL on megapap.com.")
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


def _media_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urlsplit(value.strip())
    if url.scheme == "https" and url.hostname in ALLOWED_HOSTS and not url.query and not url.username:
        return value.strip()
    return None


def parse_megapap_catalog(source: BinaryIO) -> list[dict]:
    products: list[dict] = []
    seen: set[str] = set()
    root_tag = None
    for event, node in ElementTree.iterparse(source, events=("start", "end"), forbid_dtd=True):
        if root_tag is None:
            root_tag = node.tag
            if root_tag != "megapap":
                raise ValueError("This XML is not a MEGAPAP product catalog.")
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
        products.append({
            "supplier_code": code, "supplier_sku": text("sku", 255), "ean": text("ean", 64),
            "name": name, "category": text("category"), "image_url": _media_url(text("main_image", 2000)),
            "quantity": int(Decimal(quantity)) if quantity is not None and Decimal(quantity) == int(Decimal(quantity)) else None,
            "wholesale_price_net": _number(text("wholesale_price_without_vat")),
            "retail_price_gross": _number(text("retail_price_with_vat")),
            "details": {
                "description": text("description", 50000), "availability": text("availability"),
                "manufacturer": text("manufacturer", 255), "minimum": _number(text("minimum")),
                "weboffer_price_gross": _number(text("weboffer_price_with_vat")),
                "volume_item": _number(text("volume_item")), "weight_item": _number(text("weight_item")),
                "packages_per_item": _number(text("packages_per_item")),
                "comb_width_cm": _number(text("comb_width_cm")),
                "comb_length_cm": _number(text("comb_length_cm")),
                "comb_height_cm": _number(text("comb_height_cm")),
                "filters": [{"group": (f.findtext("group") or "")[:255], "value": (f.findtext("value") or "")[:500]}
                            for f in node.findall("./filters/filter")[:100]],
                "images": [value for image in node.findall("./images/image")[:30]
                           if (value := _media_url(image.text))],
            },
        })
        node.clear()
        if len(products) > MAX_PRODUCTS:
            raise ValueError("Supplier XML exceeds the product limit.")
    if not products:
        raise ValueError("Supplier XML contains no products; the previous catalog was retained.")
    return products


def fetch_megapap_catalog(url: str) -> list[dict]:
    url = validate_feed_url(url)
    started = time.monotonic()
    # Redirects stay on the audited supplier host; no arbitrary server-side URLs.
    with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=False) as client:
        for _ in range(4):
            with client.stream("GET", url, headers={"User-Agent": "IndeMarketingAnalyzer/1.0"}) as response:
                if response.is_redirect:
                    url = validate_feed_url(urljoin(url, response.headers.get("location", "")))
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Supplier XML returned HTTP {response.status_code}.")
                total = 0
                with tempfile.TemporaryFile() as source:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > MAX_FEED_BYTES or time.monotonic() - started > 120:
                            raise ValueError("Supplier XML exceeded the size or time limit.")
                        source.write(chunk)
                    source.seek(0)
                    return parse_megapap_catalog(source)
    raise ValueError("Too many supplier XML redirects.")
