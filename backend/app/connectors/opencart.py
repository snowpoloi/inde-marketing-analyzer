from datetime import date
import io
import re
import tempfile
from typing import Any
from xml.etree import ElementTree

import httpx


DEFAULT_PRODUCT_FEED_TIMEOUT_SECONDS = 300.0


def _float_config(value: Any, default: float) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


class OpenCartConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.endpoint_url = config.get("endpoint_url")
        self.product_feed_url = config.get("product_feed_url")
        self.api_key = config.get("api_key")
        self.timeout = _float_config(config.get("timeout_seconds"), 30.0)
        self.product_feed_timeout = max(
            _float_config(config.get("product_feed_timeout_seconds"), DEFAULT_PRODUCT_FEED_TIMEOUT_SECONDS),
            self.timeout,
            DEFAULT_PRODUCT_FEED_TIMEOUT_SECONDS,
        )

    def fetch_orders(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.endpoint_url:
            raise ValueError("OpenCart endpoint_url is missing in integration settings.")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = httpx.get(
            self.endpoint_url,
            params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            orders = payload.get("orders", payload.get("data", []))
            if isinstance(orders, list):
                return orders
        raise ValueError("OpenCart endpoint must return a list or an object with orders/data list.")

    def fetch_product_catalog(self) -> list[dict[str, Any]]:
        if not self.product_feed_url:
            return []

        with httpx.stream(
            "GET",
            self.product_feed_url,
            headers={"User-Agent": "IndeMarketingAnalyzer/1.0"},
            follow_redirects=True,
            timeout=httpx.Timeout(self.product_feed_timeout, connect=min(self.product_feed_timeout, 30.0)),
        ) as response:
            response.raise_for_status()
            with tempfile.TemporaryFile() as feed_file:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    feed_file.write(chunk)
                feed_file.seek(0)
                return parse_product_feed_file(feed_file)


def _tag_name(tag: str) -> str:
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    if ":" in tag:
        tag = tag.rsplit(":", 1)[1]
    return tag.strip()


def _feed_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _tag_name(value).strip().lower()).strip("_")


def _node_text(node: ElementTree.Element) -> str | None:
    value = "".join(node.itertext()).strip()
    return value or None


def _item_fields(item: ElementTree.Element) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in item.attrib.items():
        normalized_key = _feed_key(key)
        text = str(value or "").strip()
        if normalized_key and text:
            fields.setdefault(normalized_key, text)

    for child in item:
        normalized_key = _feed_key(child.tag)
        text = _node_text(child)
        if normalized_key and text:
            fields.setdefault(normalized_key, text)
    return fields


def _field_value(fields: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = fields.get(_feed_key(name))
        if value:
            return value
    return None


def _clean_price(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).replace("\u00a0", " ").strip()
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + "." + tail
    return text or None


def _clean_category(value: str | None, shortest: str | None) -> str | None:
    if value:
        first_path = value.split("|", 1)[0].strip()
        if ">" in first_path:
            parts = [part.strip() for part in first_path.split(">") if part.strip()]
            return parts[-1] if parts else first_path
        if first_path:
            return first_path
    return shortest or None


def _product_from_item(item: ElementTree.Element) -> dict[str, Any] | None:
    fields = _item_fields(item)
    category_path = _field_value(
        fields,
        "category_path",
        "category",
        "product_type",
        "google_product_category",
        "categories",
    )
    category_shortest = _field_value(fields, "category_shortest", "category_name", "last_category")
    sku = _field_value(fields, "sku", "model", "id", "identifier", "product_id", "item_id", "offer_id", "mpn")
    if not sku:
        return None
    brand = _field_value(fields, "brand", "manufacturer", "make", "vendor")
    manufacturer = _field_value(fields, "manufacturer", "brand", "make", "vendor")
    return {
        "sku": sku,
        "model": _field_value(fields, "model", "sku", "mpn"),
        "product_id": _field_value(fields, "product_id", "productid", "identifier", "id", "item_id", "offer_id"),
        "name": _field_value(fields, "name", "title", "product_name") or sku,
        "description": _field_value(fields, "description", "short_description"),
        "brand": brand or manufacturer,
        "manufacturer": manufacturer,
        "category": _clean_category(category_path, category_shortest),
        "category_path": category_path,
        "status": _field_value(fields, "status", "availability", "stock_status"),
        "quantity": _field_value(fields, "quantity", "stock", "inventory"),
        "price": _clean_price(_field_value(fields, "price", "sale_price")),
        "link": _field_value(fields, "link", "url", "product_url"),
        "image_url": _field_value(fields, "image", "image_link", "image_url", "picture", "main_image"),
        "isbn": _field_value(fields, "isbn"),
        "upc": _field_value(fields, "upc"),
        "ean": _field_value(fields, "ean", "gtin"),
        "jan": _field_value(fields, "jan"),
        "mpn": _field_value(fields, "mpn"),
        "raw_fields": fields,
    }


def parse_product_feed_file(source: Any) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for _, item in ElementTree.iterparse(source, events=("end",)):
        if _feed_key(item.tag) not in {"item", "product", "entry", "offer", "shopitem"}:
            continue
        product = _product_from_item(item)
        if product:
            products.append(product)
        item.clear()
    return products


def parse_product_feed(content: bytes) -> list[dict[str, Any]]:
    return parse_product_feed_file(io.BytesIO(content))
