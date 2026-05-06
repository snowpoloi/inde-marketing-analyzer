from datetime import date
from typing import Any
from xml.etree import ElementTree

import httpx


class OpenCartConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.endpoint_url = config.get("endpoint_url")
        self.product_feed_url = config.get("product_feed_url")
        self.api_key = config.get("api_key")
        self.timeout = float(config.get("timeout_seconds", 30))

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

        response = httpx.get(self.product_feed_url, timeout=self.timeout)
        response.raise_for_status()
        return parse_product_feed(response.content)


def _tag_name(tag: str) -> str:
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    return tag.strip()


def _child_text(item: ElementTree.Element, tag: str) -> str | None:
    for child in item:
        if _tag_name(child.tag).lower() == tag.lower():
            value = "".join(child.itertext()).strip()
            return value or None
    return None


def _clean_category(value: str | None, shortest: str | None) -> str | None:
    if shortest:
        return shortest
    if not value:
        return None
    first_path = value.split("|", 1)[0].strip()
    if ">" in first_path:
        parts = [part.strip() for part in first_path.split(">") if part.strip()]
        return parts[-1] if parts else first_path
    return first_path or None


def parse_product_feed(content: bytes) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(content)
    products: list[dict[str, Any]] = []
    for item in root.iter():
        if _tag_name(item.tag).lower() != "item":
            continue
        category_path = _child_text(item, "Category")
        category_shortest = _child_text(item, "category_shortest")
        sku = _child_text(item, "SKU") or _child_text(item, "Model") or _child_text(item, "identifier")
        if not sku:
            continue
        manufacturer = _child_text(item, "Manufacturer")
        products.append(
            {
                "sku": sku,
                "model": _child_text(item, "Model"),
                "product_id": _child_text(item, "identifier"),
                "name": _child_text(item, "Name") or sku,
                "brand": manufacturer,
                "manufacturer": manufacturer,
                "category": _clean_category(category_path, category_shortest),
                "category_path": category_path,
                "status": _child_text(item, "Status"),
                "quantity": _child_text(item, "Quantity"),
                "price": _child_text(item, "Price"),
                "link": _child_text(item, "Link"),
                "image_url": _child_text(item, "Image"),
                "isbn": _child_text(item, "ISBN"),
                "upc": _child_text(item, "UPC"),
                "ean": _child_text(item, "EAN"),
                "jan": _child_text(item, "JAN"),
            }
        )
    return products
